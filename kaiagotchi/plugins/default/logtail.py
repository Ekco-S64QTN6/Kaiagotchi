import os
import logging
import threading
import time
from itertools import islice
from pathlib import Path
from typing import Generator, Optional
from flask import render_template_string, jsonify, abort, Response

from kaiagotchi import plugins
from kaiagotchi.utils import StatusFile

# Complete TEMPLATE definition
TEMPLATE = """
{% extends "base.html" %}
{% set active_page = "plugins" %}
{% block title %}
    Logtail
{% endblock %}

{% block styles %}
    {{ super() }}
    <style>
        * {
            box-sizing: border-box;
        }
        #filter {
            width: 100%;
            font-size: 16px;
            padding: 12px 20px 12px 40px;
            border: 1px solid #ddd;
            margin-bottom: 12px;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            border: 1px solid #ddd;
        }
        th, td {
            text-align: left;
            padding: 12px;
            width: 1px;
            white-space: nowrap;
        }
        td:nth-child(2) {
            text-align: center;
        }
        thead, tr:hover {
            background-color: #f1f1f1;
        }
        tr {
            border-bottom: 1px solid #ddd;
        }
        div.sticky {
            position: -webkit-sticky;
            position: sticky;
            top: 0;
            display: table;
            width: 100%;
        }
        div.sticky > * {
            display: table-cell;
        }
        div.sticky > span {
            width: 1%;
        }
        div.sticky > input {
            width: 100%;
        }
        tr.default {
            color: black;
        }
        tr.info {
            color: black;
        }
        tr.warning {
            color: darkorange;
        }
        tr.error {
            color: crimson;
        }
        tr.debug {
            color: blueviolet;
        }
        .ui-mobile .ui-page-active {
            overflow: visible;
            overflow-x: visible;
        }
    </style>
{% endblock %}

{% block script %}
    var table = document.getElementById('table');
    var filter = document.getElementById('filter');
    var filterVal = filter.value.toUpperCase();

    var xhr = new XMLHttpRequest();
    xhr.open('GET', '{{ url_for('plugins') }}/logtail/stream');
    xhr.send();
    var position = 0;
    var data;
    var time;
    var level;
    var msg;
    var colorClass;

    function handleNewData() {
        var messages = xhr.responseText.split('\\n');
        filterVal = filter.value.toUpperCase();
        messages.slice(position, -1).forEach(function(value) {

            if (value.charAt(0) != '[') {
                msg = value;
                time = '';
                level = '';
            } else {
                data = value.split(']');
                time = data.shift() + ']';
                level = data.shift() + ']';
                msg = data.join(']');

                switch(level) {
                    case ' [INFO]':
                        colorClass = 'info';
                        break;
                    case ' [WARNING]':
                        colorClass = 'warning';
                        break;
                    case ' [ERROR]':
                        colorClass = 'error';
                        break;
                    case ' [DEBUG]':
                        colorClass = 'debug';
                        break;
                    default:
                        colorClass = 'default';
                        break;
                }
            }

            var tr = document.createElement('tr');
            var td1 = document.createElement('td');
            var td2 = document.createElement('td');
            var td3 = document.createElement('td');

            td1.textContent = time;
            td2.textContent = level;
            td3.textContent = msg;

            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);

            tr.className = colorClass;

            if (filterVal.length > 0 && value.toUpperCase().indexOf(filterVal) == -1) {
                tr.style.display = "none";
            }

            table.appendChild(tr);
        });
        position = messages.length - 1;
    }

    var scrollingElement = (document.scrollingElement || document.body)
    function scrollToBottom () {
       scrollingElement.scrollTop = scrollingElement.scrollHeight;
    }

    var timer;
    var scrollElm = document.getElementById('autoscroll');
    timer = setInterval(function() {
        handleNewData();
        if (scrollElm.checked) {
            scrollToBottom();
        }
        if (xhr.readyState == XMLHttpRequest.DONE) {
            clearInterval(timer);
        }
    }, 1000);

    var typingTimer;
    var doneTypingInterval = 1000;

    filter.onkeyup = function() {
        clearTimeout(typingTimer);
        typingTimer = setTimeout(doneTyping, doneTypingInterval);
    }

    filter.onkeydown = function() {
        clearTimeout(typingTimer);
    }

    function doneTyping() {
        document.body.style.cursor = 'progress';
        var tr, tds, td, i, txtValue;
        filterVal = filter.value.toUpperCase();
        tr = table.getElementsByTagName("tr");
        for (i = 1; i < tr.length; i++) {
            txtValue = tr[i].textContent || tr[i].innerText;
            if (txtValue.toUpperCase().indexOf(filterVal) > -1) {
                tr[i].style.display = "table-row";
            } else {
                tr[i].style.display = "none";
            }
        }
        document.body.style.cursor = 'default';
    }
{% endblock %}

{% block content %}
    <div class="sticky">
        <input type="text" id="filter" placeholder="Search for ..." title="Type in a filter">
        <span><input checked type="checkbox" id="autoscroll"></span>
        <span><label for="autoscroll"> Autoscroll to bottom</label><br></span>
    </div>
    <table id="table">
        <thead>
            <th>
                Time
            </th>
            <th>
                Level
            </th>
            <th>
                Message
            </th>
        </thead>
    </table>
{% endblock %}
"""


class Logtail(plugins.Plugin):
    __author__ = '33197631+dadav@users.noreply.github.com'
    __version__ = '0.2.0'  # Updated version
    __license__ = 'GPL3'
    __description__ = 'This plugin tails the logfile with enhanced security and performance'

    def __init__(self):
        self.lock = threading.RLock()
        self.options = dict()
        self.ready = False
        self.max_lines = 4096
        self.log_file_path = None
        self.last_file_size = 0

    def _validate_log_file(self, filepath: str) -> bool:
        """Validate log file path and permissions"""
        try:
            path = Path(filepath)
            if not path.exists():
                logging.error(f"Logtail: Log file not found: {filepath}")
                return False
            if not path.is_file():
                logging.error(f"Logtail: Path is not a file: {filepath}")
                return False
            # Check if file is readable
            with open(filepath, 'r') as f:
                f.read(0)  # Test read
            return True
        except Exception as e:
            logging.error(f"Logtail: Error validating log file {filepath}: {e}")
            return False

    def _safe_tail_file(self, filepath: str, max_lines: int = 4096) -> list:
        """Safely tail file with error handling"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                # Get last N lines efficiently
                lines = []
                buffer_size = 8192
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                block = -1
                lines_found = 0
                
                while lines_found < max_lines and file_size > 0:
                    if file_size - buffer_size > 0:
                        f.seek(block * buffer_size, os.SEEK_END)
                        data = f.read(buffer_size)
                    else:
                        f.seek(0, os.SEEK_SET)
                        data = f.read(file_size)
                    
                    lines_found += data.count('\n')
                    lines.append(data)
                    if file_size - buffer_size > 0:
                        block -= 1
                    else:
                        break
                    file_size -= buffer_size
                
                # Return the last max_lines
                content = ''.join(reversed(lines))
                return content.split('\n')[-max_lines:]
                
        except Exception as e:
            logging.error(f"Logtail: Error reading log file: {e}")
            return []

    def on_loaded(self):
        """Plugin loaded callback"""
        logging.info("Logtail plugin loaded with enhanced security")

    def on_config_changed(self, config):
        """Enhanced config validation"""
        try:
            self.config = config
            log_path = config['main']['log']['path']
            
            if self._validate_log_file(log_path):
                self.log_file_path = log_path
                self.ready = True
                logging.info(f"Logtail: Successfully configured for log file: {log_path}")
            else:
                self.ready = False
                logging.error("Logtail: Invalid log file configuration")
                
        except KeyError as e:
            logging.error(f"Logtail: Missing configuration key: {e}")
            self.ready = False
        except Exception as e:
            logging.error(f"Logtail: Configuration error: {e}")
            self.ready = False

    def on_webhook(self, path, request):
        """Enhanced webhook with security headers"""
        if not self.ready:
            return "Plugin not ready"

        # Add security headers
        headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
        }

        if not path or path == "/":
            response = render_template_string(TEMPLATE)
            for key, value in headers.items():
                response.headers[key] = value
            return response

        if path == 'stream':
            def generate():
                if not self.log_file_path:
                    yield "Log file not configured\n"
                    return

                try:
                    # Send initial batch
                    initial_lines = self._safe_tail_file(self.log_file_path, self.max_lines)
                    yield '\n'.join(initial_lines) + '\n'
                    
                    # Stream new lines
                    while True:
                        try:
                            current_size = os.path.getsize(self.log_file_path)
                            if current_size > self.last_file_size:
                                with open(self.log_file_path, 'r') as f:
                                    f.seek(self.last_file_size)
                                    new_data = f.read()
                                    if new_data:
                                        yield new_data
                                    self.last_file_size = current_size
                            elif current_size < self.last_file_size:
                                # Log file was rotated
                                self.last_file_size = 0
                                initial_lines = self._safe_tail_file(self.log_file_path, self.max_lines)
                                yield '\n'.join(initial_lines) + '\n'
                            
                            time.sleep(1)
                        except Exception as e:
                            logging.error(f"Logtail: Stream error: {e}")
                            yield f"# Error reading log: {e}\n"
                            break
                            
                except Exception as e:
                    yield f"# Error: {e}\n"

            response = Response(generate(), mimetype='text/plain')
            for key, value in headers.items():
                response.headers[key] = value
            return response

        abort(404)