from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QPlainTextEdit


def get_widget_state(obj, config, name=None):
    #if config is None:
    #    config = conf.CONFIG
    if name is None:
        name = obj.objectName
    if isinstance(obj, QLabel):
        config[name] = str(obj.text())
    if isinstance(obj, QComboBox):
        config[name] = {'items': [str(obj.itemText(k)) for k in range(obj.count())],
                        'index': obj.currentIndex()}
    if isinstance(obj, QCheckBox):
        config[name] = obj.isChecked()
    if isinstance(obj, QPlainTextEdit):
        config[name] = obj.toPlainText()

def set_widget_state(obj, config, name=None):
    if name is None:
        name = obj.objectName

    if name not in config:
        return

    if isinstance(obj, QLabel):
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
