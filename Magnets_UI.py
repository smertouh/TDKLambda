# coding: utf-8
'''
Created on Jul 28, 2019

@author: sanin
''' 

import os.path
import sys
import json
import logging
import zipfile
import time

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import qApp
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtWidgets import QTableWidget
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QSpinBox
from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtWidgets import QLineEdit
from PyQt5 import uic
from PyQt5.QtCore import QSize
from PyQt5.QtCore import QPoint
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtGui import QBrush
from PyQt5.QtGui import QFont
import PyQt5.QtGui as QtGui
import PyQt5

import tango
#from taurus.external.qt import Qt
#from taurus.qt.qtgui.application import TaurusApplication
#from taurus.qt.qtgui.display import TaurusLabel

ORGANIZATION_NAME = 'BINP'
APPLICATION_NAME = 'Magnets_UI'
APPLICATION_NAME_SHORT = 'Magnets_UI'
APPLICATION_VERSION = '1_0'
CONFIG_FILE = APPLICATION_NAME_SHORT + '.json'
UI_FILE = APPLICATION_NAME_SHORT + '.ui'

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
f_str = '%(asctime)s %(funcName)s(%(lineno)s) ' + \
        '%(levelname)-7s %(message)s'
log_formatter = logging.Formatter(f_str, datefmt='%H:%M:%S')
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# Global configuration dictionary
CONFIG = {}


def print_exception_info(level=logging.DEBUG):
    logger.log(level, "Exception ", exc_info=True)


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        global logger
        # Initialization of the superclass
        super(MainWindow, self).__init__(parent)

        # logging config
        self.logger = logger
        # members definition
        self.refresh_flag = False
        self.last_selection = -1
        self.elapsed = 0

        # Load the UI
        uic.loadUi(UI_FILE, self)
        # Default main window parameters
        #self.setMinimumSize(QSize(480, 640))       # min size
        self.resize(QSize(480, 640))                # size
        self.move(QPoint(50, 50))                   # position
        self.setWindowTitle(APPLICATION_NAME)       # title
        self.setWindowIcon(QtGui.QIcon('icon.png')) # icon
        # Connect signals with slots
        ##self.plainTextEdit_1.textChanged.connect(self.refresh_on)
        #self.checkBox_25.clicked.connect(self.phandler)
        #self.doubleSpinBox_21.editingFinished.connect(self.phandler)
        #self.doubleSpinBox_21.setKeyboardTracking(False)
        # Menu actions connection
        self.actionQuit.triggered.connect(qApp.quit)
        self.actionPlot.triggered.connect(self.show_main_pane)
        self.actionParameters.triggered.connect(self.show_param_pane)
        self.actionAbout.triggered.connect(self.show_about)
        # Additional decorations
        ##self.radioButton.setStyleSheet('QRadioButton {background-color: red}')
        ##self.doubleSpinBox_4.setSingleStep(0.1)
        # Clock at status bar
        self.clock = QLabel(" ")
        self.statusBar().addPermanentWidget(self.clock)

        print(APPLICATION_NAME + ' version ' + APPLICATION_VERSION + ' started')

        # find all controls in config tab
        self.config_widgets = []
        self.get_widgets(self.tabWidgetPage3)

        self.restore_settings(self.config_widgets)

        # attribute list
        self.atts = (('sys/tg_test/1/boolean_scalar', self.checkBox_26),
                     ('sys/tg_test/1/double_scalar', self.label_63),
                     ('sys/tg_test/1/double_scalar_w', self.label_65),
                     )
        self.watts = (('sys/tg_test/1/double_scalar_w', self.doubleSpinBox_21),
                     ('sys/tg_test/1/boolean_scalar', self.checkBox_25),
                     ('sys/tg_test/1/long_scalar_w', self.doubleSpinBox_20),
                     )
        self.atps = []
        for at in self.atts:
            try:
                ap = tango.AttributeProxy(at[0])
                self.atps.append((ap, at[1]))
            except:
                pass
        self.watps = []
        for at in self.watts:
            try:
                ap = tango.AttributeProxy(at[0])
                self.watps.append((ap, at[1]))
                v = ap.read()
                if hasattr(at[1], 'setValue'):
                    at[1].setValue(v.value)
                if hasattr(at[1], 'setChecked'):
                    at[1].setChecked(v.value)
            except:
                print_exception_info()
                pass
        for w in self.watps:
            if isinstance(w[1], QCheckBox):
                w[1].stateChanged.connect(self.sb_changed)
            if isinstance(w[1], QSpinBox):
                w[1].clicked.connect(self.sb_changed)

        self.n = 0

        self.wap = tango.AttributeProxy('sys/tg_test/1/double_scalar_w')

    def get_widgets(self, obj, s=''):
        lout = obj.layout()
        for k in range(lout.count()):
            wgt = lout.itemAt(k).widget()
            #print(s, wgt)
            if wgt is not None and wgt not in self.config_widgets:
                self.config_widgets.append(wgt)
            if isinstance(wgt, QtWidgets.QFrame):
                self.get_widgets(wgt, s=s + '   ')

    def show_about(self):
        QMessageBox.information(self, 'About', APPLICATION_NAME + ' Version ' + APPLICATION_VERSION +
                                '\nUser interface program to control TDK Lambda Genesis power supplies.', QMessageBox.Ok)

    def show_main_pane(self):
        self.stackedWidget.setCurrentIndex(0)
        self.actionPlot.setChecked(True)
        self.actionLog.setChecked(False)
        self.actionParameters.setChecked(False)

    def show_param_pane(self):
        self.stackedWidget.setCurrentIndex(2)
        self.actionPlot.setChecked(False)
        self.actionLog.setChecked(False)
        self.actionParameters.setChecked(True)

    def log_level_changed(self, m):
        levels = [logging.NOTSET, logging.DEBUG, logging.INFO,
                  logging.WARNING, logging.ERROR, logging.CRITICAL]
        if m >= 0:
            self.logger.setLevel(levels[m])

    def phandler(self, *args, **kwargs):
        print(args, kwargs)

    def sb_changed(self, value):
        #print(value)
        wgt = self.focusWidget()
        if isinstance(wgt, QCheckBox):
            value = bool(value)
        for w in self.watps:
            if wgt == w[1]:
                try:
                    w[0].write(value)
                except:
                    print_exception_info()
                    #print('except')

    def onQuit(self) :
        # Save global settings
        self.save_settings(self.config_widgets)
        timer.stop()
        
    def save_settings(self, widgets=(), file_name=CONFIG_FILE) :
        global CONFIG
        try:
            # Save window size and position
            p = self.pos()
            s = self.size()
            CONFIG['main_window'] = {'size':(s.width(), s.height()), 'position':(p.x(), p.y())}
            #get_state(self.comboBox_1, 'comboBox_1')
            for w in widgets:
                get_widget_state(w, CONFIG)
            with open(file_name, 'w') as configfile:
                configfile.write(json.dumps(CONFIG, indent=4))
            self.logger.info('Configuration saved to %s' % file_name)
            return True
        except :
            self.logger.log(logging.WARNING, 'Configuration save error to %s' % file_name)
            print_exception_info()
            return False
        
    def restore_settings(self, widgets=(), file_name=CONFIG_FILE) :
        global CONFIG
        try :
            with open(file_name, 'r') as configfile:
                s = configfile.read()
            CONFIG = json.loads(s)
            # Restore log level
            if 'log_level' in CONFIG:
                v = CONFIG['log_level']
                self.logger.setLevel(v)
                levels = [logging.NOTSET, logging.DEBUG, logging.INFO,
                          logging.WARNING, logging.ERROR, logging.CRITICAL, logging.CRITICAL+10]
                for m in range(len(levels)):
                    if v < levels[m]:
                        break
                self.comboBox_1.setCurrentIndex(m-1)
            # Restore window size and position
            if 'main_window' in CONFIG:
                self.resize(QSize(CONFIG['main_window']['size'][0], CONFIG['main_window']['size'][1]))
                self.move(QPoint(CONFIG['main_window']['position'][0], CONFIG['main_window']['position'][1]))
            #set_state(self.plainTextEdit_1, 'plainTextEdit_1')
            #set_state(self.comboBox_1, 'comboBox_1')
            self.logger.log(logging.INFO, 'Configuration restored from %s' % file_name)
            for w in widgets:
                set_widget_state(w, CONFIG)
            return True
        except :
            self.logger.log(logging.WARNING, 'Configuration restore error from %s' % file_name)
            print_exception_info()
            return False

    def timer_handler(self):
        t0 = time.time()
        self.elapsed += 1
        t = time.strftime('%H:%M:%S')
        self.clock.setText('Elapsed: %ds    %s' % (self.elapsed, t))
        count = 0
        while time.time() - t0 < 0.25:
            if isinstance(self.atps[self.n][1], QLabel):
                lbl_update(self.atps[self.n][1], self.atps[self.n][0])
            if isinstance(self.atps[self.n][1], QCheckBox):
                cb_update(self.atps[self.n][1], self.atps[self.n][0])
            self.n += 1
            if self.n >= len(self.atps):
                self.n = 0
            count += 1
            if count == len(self.atps):
                break
        #print(int((time.time()-t0)*1000.0), 'ms')
        #time.sleep(1.0)


def cb_switch_color(cb: QCheckBox, m, colors=('green', 'red')):
    if isinstance(m, bool):
        if m:
            cb.setStyleSheet('QCheckBox::indicator { background: ' + colors[0] + ';}')
        else:
            cb.setStyleSheet('QCheckBox::indicator { background: ' + colors[1] + ';}')
            # cb.setStyleSheet('QCheckBox::indicator { background: red;}')
    if isinstance(m, str):
        cb.setStyleSheet('QCheckBox::indicator { background: ' + m + ';}')

def cb_update(cb: QCheckBox, attr_proxy: tango.AttributeProxy):
    try:
        attr = attr_proxy.read()
        value = attr.value
        if attr.type == tango._tango.CmdArgType.DevBoolean and attr.data_format == tango._tango.AttrDataFormat.SCALAR:
            if attr.quality == tango._tango.AttrQuality.ATTR_VALID:
                cb_switch_color(cb, value)
            else:
                cb_switch_color(cb, 'gray')
        else:
            print('Not scalar boolean attribute for QCheckBox')
            cb_switch_color(cb, 'gray')
    except:
        cb_switch_color(cb, 'gray')
        #cb.setStyleSheet('border: red')

def lbl_update(lbl: QLabel, attr_proxy: tango.AttributeProxy):
    try:
        attr = attr_proxy.read()
        ac = attr_proxy.get_config()
        value = ac.format % attr.value
        if attr.data_format == tango._tango.AttrDataFormat.SCALAR:
            if attr.quality == tango._tango.AttrQuality.ATTR_VALID:
                lbl.setText(value)
                #lbl.setStyleSheet('background: green; color: blue')
            else:
                lbl.setText(value)
                lbl.setStyleSheet('color: red')
                #lbl.setStyleSheet('background: red')
        else:
            print('Not scalar attribute for QLabel')
            lbl.setText('****')
            lbl.setStyleSheet('color: red')
    except:
        lbl.setText('****')
        lbl.setStyleSheet('color: red')


def get_widget_state(obj, config, name=None):
    try:
        if name is None:
            name = obj.objectName()
        if isinstance(obj, QLineEdit):
            config[name] = str(obj.text())
        if isinstance(obj, QComboBox):
            config[name] = {'items': [str(obj.itemText(k)) for k in range(obj.count())],
                            'index': obj.currentIndex()}
        if isinstance(obj, QCheckBox):
            config[name] = obj.isChecked()
        if isinstance(obj, QPlainTextEdit):
            config[name] = obj.toPlainText()
    except:
        return

def set_widget_state(obj, config, name=None):
    try:
        if name is None:
            name = obj.objectName()
        if name not in config:
            return
        if isinstance(obj, QLineEdit):
            obj.setText(config[name])
        if isinstance(obj, QComboBox):
            obj.setUpdatesEnabled(False)
            obj.blockSignals(True)
            obj.clear()
            obj.addItems(config[name]['items'])
            obj.blockSignals(False)
            obj.setUpdatesEnabled(True)
            obj.setCurrentIndex(config[name]['index'])
            # Force index change event in the case of index=0
            if config[name]['index'] == 0:
                obj.currentIndexChanged.emit(0)
        if isinstance(obj, QCheckBox):
            obj.setChecked(config[name])
        if isinstance(obj, QPlainTextEdit):
            obj.setPlainText(config[name])
    except:
        return

if __name__ == '__main__':
    # Create the GUI application
    app = QApplication(sys.argv)
    # Instantiate the main window
    dmw = MainWindow()
    app.aboutToQuit.connect(dmw.onQuit)
    # Show it
    dmw.show()
    # Defile and start timer task
    timer = QTimer()
    timer.timeout.connect(dmw.timer_handler)
    timer.start(200)
    # Start the Qt main loop execution, exiting from this script
    # with the same return code of Qt application
    sys.exit(app.exec_())
