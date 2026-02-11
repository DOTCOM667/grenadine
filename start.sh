#!/bin/bash
pip3 install -r requirements.txt
playwright install chromium
python3 app.py
