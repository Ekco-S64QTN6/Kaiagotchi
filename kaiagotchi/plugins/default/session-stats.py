import os
import logging
import threading
from time import sleep
from datetime import datetime,timedelta
from kaiagotchi import plugins
from kaiagotchi.utils import StatusFile
from flask import render_template_string
from flask import jsonify

TEMPLATE = """
{% extends "base.html" %}
{% set active_page = "plugins" %}
{% block title %}
    Session stats
{% endblock %}

{% block styles %}
    {{ super() }}
    <link rel="stylesheet" href="/css/jquery.jqplot.min.css"/>
    <link rel="stylesheet" href="/css/jquery.jqplot.css"/>
    <style>
        div.chart {
            height: 400px;
            width: 100%;
        }
        div#session {
            width: 100%;
        }
    </style>
{% endblock %}

{% block scripts %}
    {{ super() }}
     <script type="text/javascript" src="/js/jquery.jqplot.min.js"></script>
     <script type="text/javascript" src="/js/jquery.jqplot.js"></script>
     <script type="text/javascript" src="/js/plugins/jqplot.mobile.js"></script>
     <script type="text/javascript" src="/js/plugins/jqplot.json2.js"></script>
     <script type="text/javascript" src="/js/plugins/jqplot.dateAxisRenderer.js"></script>
     <script type="text/javascript" src="/js/plugins/jqplot.highlighter.js"></script>
     <script type="text/javascript" src="/js/plugins/jqplot.cursor.js"></script>
     <script type="text/javascript" src="/js/plugins/jqplot.enhancedLegendRenderer.js"></script>
{% endblock %}

{% block script %}
    $(document).ready(function(){
        var ajaxDataRenderer = function(url, plot, options) {
        var ret = null;
        $.ajax({
            async: false,
            url: url,
            dataType:"json",
            success: function(data) {
                ret = data;
            }
        });
        return ret;
        };

    function loadFiles(url, elm) {
        var data = ajaxDataRenderer(url);
        var x = document.getElementById(elm);
        $.each(data['files'], function( index, value ) {
            var option = document.createElement("option");
            option.text = value;
            x.add(option);
        });
    }

    function loadData(url, elm, title, fill) {
        var data = ajaxDataRenderer(url);
        var plot_os = $.jqplot(elm, data.values,{
        title: title,
        stackSeries: fill,
        seriesDefaults: {
            showMarker: !fill,
            fill: fill,
            fillAndStroke: fill
        },
        legend: {
            show: true,
            renderer: $.jqplot.EnhancedLegendRenderer,
            placement: 'outsideGrid',
            labels: data.labels,
            location: 's',
            rendererOptions: {
                numberRows: '2',
            },
            rowSpacing: '0px'
        },
        axes:{
            xaxis:{
                renderer:$.jqplot.DateAxisRenderer,
                tickOptions:{formatString:'%H:%M:%S'}
            },
            yaxis:{
                tickOptions:{formatString:'%.2f'}
            }
        },
        highlighter: {
            show: true,
            sizeAdjust: 7.5
        },
        cursor:{
            show: true,
            tooltipLocation:'sw'
        }
        }).replot({
        axes:{
            xaxis:{
                renderer:$.jqplot.DateAxisRenderer,
                tickOptions:{formatString:'%H:%M:%S'}
            },
            yaxis:{
                tickOptions:{formatString:'%.2f'}
            }
        }
        });
    }

    function loadSessionFiles() {
        loadFiles('/plugins/session-stats/session', 'session');
        $("#session").change(function() {
            loadSessionData();
        });
    }

    function loadSessionData() {
        var x = document.getElementById("session");
        var session = x.options[x.selectedIndex].text;
        loadData('/plugins/session-stats/os' + '?session=' + session, 'chart_os', 'OS', false)
        loadData('/plugins/session-stats/temp' + '?session=' + session, 'chart_temp', 'Temp', false)
        loadData('/plugins/session-stats/wifi' + '?session=' + session, 'chart_wifi', 'Wifi', true)
        loadData('/plugins/session-stats/duration' + '?session=' + session, 'chart_duration', 'Sleeping', true)
        loadData('/plugins/session-stats/reward' + '?session=' + session, 'chart_reward', 'Reward', false)
        loadData('/plugins/session-stats/epoch' + '?session=' + session, 'chart_epoch', 'Epochs', false)
    }


    loadSessionFiles();
    loadSessionData();
    setInterval(loadSessionData, 60000);
    });
{% endblock %}

{% block content %}
    <select id="session">
        <option selected>Current</option>
    </select>
    <div id="chart_os" class="chart"></div>
    <div id="chart_temp" class="chart"></div>
    <div id="chart_wifi" class="chart"></div>
    <div id="chart_duration" class="chart"></div>
    <div id="chart_reward" class="chart"></div>
    <div id="chart_epoch" class="chart"></div>
{% endblock %}
"""

class GhettoClock:
    def __init__(self):
        self.lock = threading.Lock()
        self._track = datetime.now()
        self._counter_thread = threading.Thread(target=self.counter)
        self._counter_thread.daemon = True
        self._counter_thread.start()

    def counter(self):
        while True:
            with self.lock:
                self._track += timedelta(seconds=1)
            sleep(1)

    def now(self):
        with self.lock:
            return self._track


class SessionStats(plugins.Plugin):
    __author__ = '33197631+dadav@users.noreply.github.com'
    __version__ = '0.1.0'
    __license__ = 'GPL3'
    __description__ = 'This plugin displays stats of the current session.'

    def __init__(self):
        self.lock = threading.RLock()  # Enhanced: Use RLock for nested operations
        self.options = dict()
        self.stats = dict()
        self.clock = GhettoClock()
        # Enhanced: Memory management
        self.max_data_points = 1000  # Prevent memory exhaustion

    def on_loaded(self):
        """
        Gets called when the plugin gets loaded
        """
        os.makedirs(self.options['save_directory'], exist_ok=True)
        self.session_name = "stats_{}.json".format(self.clock.now().strftime("%Y_%m_%d_%H_%M"))
        self.session = StatusFile(os.path.join(self.options['save_directory'],
                                               self.session_name),
                                  data_format='json')
        logging.info("Session-stats plugin loaded.")

    def on_epoch(self, agent, epoch, epoch_data):
        """
        Enhanced: Save the epoch_data to self.stats with memory management
        """
        with self.lock:
            current_time = self.clock.now().strftime("%H:%M:%S")
            self.stats[current_time] = epoch_data
            
            # Enhanced: Enforce memory limits
            if len(self.stats) > self.max_data_points:
                # Remove oldest entries
                oldest_keys = sorted(self.stats.keys())[:len(self.stats) - self.max_data_points]
                for key in oldest_keys:
                    del self.stats[key]
                    
            self.session.update(data={'data': self.stats})

    @staticmethod
    def extract_key_values(data, subkeys):
        """
        Enhanced: Extract with data validation
        """
        result = {'values': [], 'labels': subkeys}
        
        for plot_key in subkeys:
            series_data = []
            for timestamp, epoch_data in data.items():
                if plot_key in epoch_data and epoch_data[plot_key] is not None:
                    try:
                        # Validate numeric data
                        value = float(epoch_data[plot_key])
                        series_data.append([timestamp, value])
                    except (ValueError, TypeError):
                        logging.debug(f"Invalid data for {plot_key} at {timestamp}")
                        continue
            result['values'].append(series_data)
        
        return result

    def on_webhook(self, path, request):
        if not path or path == "/":
            return render_template_string(TEMPLATE)

        session_param = request.args.get('session')

        if path == "os":
            extract_keys = ['cpu_load','mem_usage',]
        elif path == "temp":
            extract_keys = ['temperature']
        elif path == "wifi":
            extract_keys = [
                'missed_interactions',
                'num_hops',
                'num_peers',
                'tot_bond',
                'avg_bond',
                'num_deauths',
                'num_associations',
                'num_handshakes',
            ]
        elif path == "duration":
            extract_keys = [
                'duration_secs',
                'slept_for_secs',
            ]
        elif path == "reward":
            extract_keys = [
                'reward',
            ]
        elif path == "epoch":
            extract_keys = [
                'active_for_epochs',
            ]
        elif path == "session":
            try:
                files = os.listdir(self.options['save_directory'])
                return jsonify({'files': files})
            except OSError as e:
                logging.error(f"Error listing session files: {e}")
                return jsonify({'files': []})

        with self.lock:
            data = self.stats
            if session_param and session_param != 'Current':
                try:
                    file_stats = StatusFile(os.path.join(self.options['save_directory'], session_param), data_format='json')
                    data = file_stats.data_field_or('data', default=dict())
                except Exception as e:
                    logging.error(f"Error loading session data: {e}")
                    return jsonify({'values': [], 'labels': extract_keys})
            
            return jsonify(SessionStats.extract_key_values(data, extract_keys))