#!/usr/bin/env python3
"""
Polyglot v2 node server OpenWeatherMap weather data
Copyright (C) 2018 Robert Paauwe
"""
import polyinterface
import sys
import time
import datetime
import urllib3
import socket
import math
import json
import write_profile
import owm_daily

LOGGER = polyinterface.LOGGER

class Controller(polyinterface.Controller):
    id = 'weather'
    #id = 'controller'
    hint = [0,0,0,0]
    def __init__(self, polyglot):
        super(Controller, self).__init__(polyglot)
        self.name = 'OpenWeatherMap'
        self.address = 'weather'
        self.primary = self.address
        self.location = ''
        self.apikey = ''
        self.units = 'metric'
        self.configured = False
        self.myConfig = {}
        self.latitude = 0
        self.fcast = {}

        self.poly.onConfig(self.process_config)

    # Process changes to customParameters
    def process_config(self, config):
        if 'customParams' in config:
            # Check if anything we care about was changed...
            if config['customParams'] != self.myConfig:
                changed = False
                if 'Location' in config['customParams']:
                    if self.location != config['customParams']['Location']:
                        self.location = config['customParams']['Location']
                        changed = True
                if 'APIkey' in config['customParams']:
                    if self.apikey != config['customParams']['APIkey']:
                        self.apikey = config['customParams']['APIkey']
                        changed = True
                if 'Units' in config['customParams']:
                    if self.units != config['customParams']['Units']:
                        self.units = config['customParams']['Units']
                        changed = True
                        self.set_driver_units()

                self.myConfig = config['customParams']
                if changed:
                    self.removeNoticesAll()
                    self.configured = True

                    if self.location == '':
                        self.addNotice("Location parameter must be set");
                        self.configured = False
                    if self.apikey == '':
                        self.addNotice("OpenWeatherMap API ID must be set");
                        self.configured = False

    def start(self):
        LOGGER.info('Starting node server')
        for day in range(1,6):
            address = 'forecast_' + str(day)
            title = 'Forecast ' + str(day)
            try:
                node = owm_daily.DailyNode(self, self.address, address, title)
                self.addNode(node)
            except:
                LOGGER.error('Failed to create forecast node ' + title)

        self.check_params()
        # TODO: Discovery
        LOGGER.info('Node server started')

        # Do an initial query to get filled in as soon as possible
        self.query_conditions()
        self.query_forecast()

    def longPoll(self):
        self.query_forecast()

    def shortPoll(self):
        self.query_conditions()

    def query_conditions(self):
        # Query for the current conditions. We can do this fairly
        # frequently, probably as often as once a minute.
        #
        # By default JSON is returned
        # http://api.openweathermap.org/data/2.5/weather?

        request = 'http://api.openweathermap.org/data/2.5/weather?'
        # TODO: handle other methods of setting location
        request += 'zip=' + self.location
        request += '&units=' + self.units
        request += '&appid=' + self.apikey

        LOGGER.debug('request = %s' % request)

        if not self.configured:
            LOGGER.info('Skipping connection because we aren\'t configured yet.')
            return

        http = urllib3.PoolManager()
        c = http.request('GET', request)
        wdata = c.data
        jdata = json.loads(wdata.decode('utf-8'))
        c.close()

        self.latitude = jdata['coord']['lat']

        # Query UV index data
        request = 'http://api.openweathermap.org/data/2.5/uvi?'
        request += 'appid=' + self.apikey
        # Only query by lat/lon so need to pull that from jdata
        request += '&lat=' + str(jdata['coord']['lat'])
        request += '&lon=' + str(jdata['coord']['lon'])
        c = http.request('GET', request)
        uv_data = json.loads(c.data.decode('utf-8'))
        c.close()
        LOGGER.debug('UV index = %f' % uv_data['value'])

        # for kicks, lets try getting pollution info
        request = 'http://api.openweathermap.org/pollution/v1/co/'
        request += str(jdata['coord']['lat']) + ','
        request += str(jdata['coord']['lon'])
        request += '/current.json?'
        request += 'appid=' + self.apikey
        # Only query by lat/lon so need to pull that from jdata
        LOGGER.debug(request)
        c = http.request('GET', request)
        pollution_data = json.loads(c.data.decode('utf-8'))
        c.close()
        LOGGER.debug(pollution_data)

        http.clear()


        LOGGER.debug(jdata)

        # Assume we always get the main section with data
        self.setDriver('CLITEMP', float(jdata['main']['temp']),
                report=True, force=False)
        self.setDriver('CLIHUM', float(jdata['main']['humidity']),
                report=True, force=False)
        self.setDriver('BARPRES', float(jdata['main']['pressure']),
                report=True, force=False)
        self.setDriver('GV0', float(jdata['main']['temp_max']),
                report=True, force=False)
        self.setDriver('GV1', float(jdata['main']['temp_min']),
                report=True, force=False)
        if 'wind' in jdata:
            self.setDriver('GV4', float(jdata['wind']['speed']),
                    report=True, force=False)
            try:
                self.setDriver('WINDDIR', float(jdata['wind']['deg']),
                    report=True, force=False)
            except:
                LOGGER.debug('missing data for wind direction')
        if 'visibility' in jdata:
            self.setDriver('GV15', float(jdata['visibility']),
                    report=True, force=False)
        if 'rain' in jdata:
            self.setDriver('GV6', float(jdata['rain']['3h']),
                    report=True, force=False)
        if 'clouds' in jdata:
            self.setDriver('GV14', float(jdata['clouds']['all']),
                    report=True, force=False)
        if 'weather' in jdata:
            self.setDriver('GV13', jdata['weather'][0]['id'],
                    report=True, force=False)
        
        self.setDriver('GV16', float(uv_data['value']), True, False)

    def query_forecast(self):
        # Three hour forecast for 5 days (or about 30 entries). This
        # is probably too much data to send to the ISY and there isn't
        # really a good way to deal with this. Would it make sense
        # to pick one of the entries for the day and just use that?

        request = 'http://api.openweathermap.org/data/2.5/forecast?'
        # TODO: handle other methods of setting location
        request += 'zip=' + self.location
        request += '&units=' + self.units
        request += '&appid=' + self.apikey

        LOGGER.debug('request = %s' % request)

        if not self.configured:
            LOGGER.info('Skipping connection because we aren\'t configured yet.')
            return

        http = urllib3.PoolManager()
        c = http.request('GET', request)
        wdata = c.data
        c.close()
        http.clear()

        jdata = json.loads(wdata.decode('utf-8'))

        #LOGGER.debug(jdata)

        # Records are for 3 hour intervals starting at midnight UTC time
        # this makes it difficult to map to local day forecasts.
        day = 1
        if 'list' in jdata:
            for forecast in jdata['list']:

                # we need to look at every 3 hr entry and build the 
                # temp and humidity min/max and also average for pressure
                # and wind speed. Looking at only the first 3 hrs isn't
                # really usefull
                dt = forecast['dt_txt'].split(' ')

                LOGGER.info('date and time: %s %s' % (dt[0], dt[1]))
                #if dt[1] != '12:00:00':
                #    continue

                if dt[1] == '00:00:00':
                    # Initialize values
                    self.fcast['temp_max'] = float(forecast['main']['temp_max'])
                    self.fcast['temp_min'] = float(forecast['main']['temp_min'])
                    self.fcast['Hmax'] = float(forecast['main']['humidity'])
                    self.fcast['Hmin'] = float(forecast['main']['humidity'])
                    self.fcast['pressure'] = float(forecast['main']['pressure'])
                    self.fcast['weather'] = float(forecast['weather'][0]['id'])
                    self.fcast['speed'] = float(forecast['wind']['speed'])
                    self.fcast['clouds'] = float(forecast['clouds']['all'])
                    self.fcast['dt'] = forecast['dt']
                else:
                    # check for high/low
                    if float(forecast['main']['temp_max']) > self.fcast['temp_max']:
                        self.fcast['temp_max'] = float(forecast['main']['temp_max'])
                    if float(forecast['main']['temp_min']) < self.fcast['temp_min']:
                        self.fcast['temp_min'] = float(forecast['main']['temp_min'])
                    if float(forecast['main']['humidity']) > self.fcast['Hmax']:
                        self.fcast['Hmax'] = float(forecast['main']['humidity'])
                    if float(forecast['main']['humidity']) < self.fcast['Hmin']:
                        self.fcast['Hmin'] = float(forecast['main']['humidity'])

                    self.fcast['pressure'] += float(forecast['main']['pressure'])
                    self.fcast['speed'] += float(forecast['wind']['speed'])
                    self.fcast['clouds'] += float(forecast['clouds']['all'])

                    # sum for averages

                if dt[1] == '21:00:00':
                    self.fcast['pressure'] /= 8
                    self.fcast['speed'] /= 8
                    self.fcast['clouds'] /= 8
                    LOGGER.info(self.fcast)
                    # Update the forecast
                    address = 'forecast_' + str(day)
                    #self.nodes[address].update_forecast(forecast, self.latitude, 400, 0.23, self.units)
                    self.nodes[address].update_forecast(self.fcast, self.latitude, 400, 0.23, self.units)
                    day += 1


    def query(self):
        for node in self.nodes:
            self.nodes[node].reportDrivers()

    def discover(self, *args, **kwargs):
        # Create any additional nodes here
        LOGGER.info("In Discovery...")

    # Delete the node server from Polyglot
    def delete(self):
        LOGGER.info('Removing node server')

    def stop(self):
        LOGGER.info('Stopping node server')

    def update_profile(self, command):
        st = self.poly.installprofile()
        return st

    def check_params(self):

        if 'Location' in self.polyConfig['customParams']:
            self.location = self.polyConfig['customParams']['Location']
        if 'APIkey' in self.polyConfig['customParams']:
            self.apikey = self.polyConfig['customParams']['APIkey']
        if 'Units' in self.polyConfig['customParams']:
            self.units = self.polyConfig['customParams']['Units']
        else:
            self.units = 'metric';

        self.configured = True

        self.addCustomParam( {
            'Location': self.location,
            'APIkey': self.apikey,
            'Units': self.units } )

        LOGGER.info('api id = %s' % self.apikey)

        self.removeNoticesAll()
        if self.location == '':
            self.addNotice("Location parameter must be set");
            self.configured = False
        if self.apikey == '':
            self.addNotice("OpenWeatherMap API ID must be set");
            self.configured = False

        self.set_driver_units()

    def set_driver_units(self):
        LOGGER.info('Configure drivers ---')
        if self.units == 'metric':
            for driver in self.drivers:
                if driver['driver'] == 'CLITEMP': driver['uom'] = 4
                if driver['driver'] == 'DEWPT': driver['uom'] = 4
                if driver['driver'] == 'GV0': driver['uom'] = 4
                if driver['driver'] == 'GV1': driver['uom'] = 4
                if driver['driver'] == 'GV2': driver['uom'] = 4
                if driver['driver'] == 'GV3': driver['uom'] = 4
                if driver['driver'] == 'GV4': driver['uom'] = 49
                if driver['driver'] == 'GV5': driver['uom'] = 49
            for day in range(1,6):
                address = 'forecast_' + str(day)
                self.nodes[address].set_units('metric')
        else:  # imperial
            for driver in self.drivers:
                if driver['driver'] == 'CLITEMP': driver['uom'] = 17
                if driver['driver'] == 'DEWPT': driver['uom'] = 17
                if driver['driver'] == 'GV0': driver['uom'] = 17
                if driver['driver'] == 'GV1': driver['uom'] = 17
                if driver['driver'] == 'GV2': driver['uom'] = 17
                if driver['driver'] == 'GV3': driver['uom'] = 17
                if driver['driver'] == 'GV4': driver['uom'] = 48
                if driver['driver'] == 'GV5': driver['uom'] = 48
            for day in range(1,6):
                address = 'forecast_' + str(day)
                self.nodes[address].set_units('imperial')

        # Write out a new node definition file here.
        write_profile.write_profile(LOGGER, self.drivers, self.nodes['forecast_1'].drivers)
        self.poly.installprofile()

    def remove_notices_all(self, command):
        self.removeNoticesAll()


    commands = {
            'DISCOVER': discover,
            'UPDATE_PROFILE': update_profile,
            'REMOVE_NOTICES_ALL': remove_notices_all
            }

    # For this node server, all of the info is available in the single
    # controller node.
    #
    # TODO: Do we want to try and do evapotranspiration calculations? 
    #       maybe later as an enhancement.
    # TODO: Add forecast data
    drivers = [
            {'driver': 'ST', 'value': 1, 'uom': 2},   # node server status
            {'driver': 'CLITEMP', 'value': 0, 'uom': 4},   # temperature
            {'driver': 'CLIHUM', 'value': 0, 'uom': 22},   # humidity
            {'driver': 'BARPRES', 'value': 0, 'uom': 118}, # pressure
            {'driver': 'WINDDIR', 'value': 0, 'uom': 76},  # direction
            {'driver': 'GV0', 'value': 0, 'uom': 4},       # max temp
            {'driver': 'GV1', 'value': 0, 'uom': 4},       # min temp
            {'driver': 'GV4', 'value': 0, 'uom': 49},      # wind speed
            {'driver': 'GV6', 'value': 0, 'uom': 82},      # rain
            {'driver': 'GV11', 'value': 0, 'uom': 27},     # climate coverage
            {'driver': 'GV12', 'value': 0, 'uom': 70},     # climate intensity
            {'driver': 'GV13', 'value': 0, 'uom': 25},     # climate conditions
            {'driver': 'GV14', 'value': 0, 'uom': 22},     # cloud conditions
            {'driver': 'GV15', 'value': 0, 'uom': 38},     # visibility
            {'driver': 'GV16', 'value': 0, 'uom': 71},     # UV index
            ]


    
if __name__ == "__main__":
    try:
        polyglot = polyinterface.Interface('OWM')
        polyglot.start()
        control = Controller(polyglot)
        control.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
        

