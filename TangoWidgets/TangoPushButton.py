# coding: utf-8
'''
Created on Jan 3, 2020

@author: sanin
'''
from PyQt5.QtWidgets import QPushButton
from TangoWidgets.TangoWriteWidget import TangoWriteWidget


class TangoPushButton(TangoWriteWidget):
    def __init__(self, name, widget: QPushButton, readonly=False):
        super().__init__(name, widget, readonly)
        self.widget.clicked.connect(self.callback)

    def set_widget_value(self):
        self.widget.setChecked(bool(self.attr.value))
        return self.attr.value

    def write(self, value):
        if self.readonly:
            return
        self.attr_proxy.write(int(value))
