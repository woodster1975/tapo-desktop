STYLE = '''
QWidget { font-family: Lato; font-size: 14px; color: #192c27; }
QMainWindow, QDialog { background: #f4f5f2; }
QLabel { background: transparent; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#brand { font-size: 22px; font-weight: 700; }
QLabel#section { font-size: 18px; font-weight: 700; }
QLabel#muted { color: #50645c; font-size: 13px; }
QLabel#status { color: #50645c; padding: 8px 0; }
QLabel#error { color: #a13e34; }
QFrame#rail { background: #e9ece6; border: none; }
QFrame#stage { background: #121b18; border-radius: 12px; }
QFrame#stage QLabel { color: #f3f6f1; }
QFrame#stage QLabel#stageHint { color: #b8cbc1; font-size: 14px; }
QFrame#cameraTile { background: #121b18; border: 1px solid #50645c; border-radius: 8px; }
QFrame#cameraTile:focus { border: 2px solid #b8cbc1; }
QLabel#tileTitle { font-weight: 700; color: #f3f6f1; }
QLabel#tileStatus { color: #b8cbc1; font-size: 12px; }
QLabel#tileHint { color: #b8cbc1; }
QWidget#cameraWallCanvas, QScrollArea#cameraWallScroll { background: #121b18; }
QFrame#stage QLabel#stageTitle { color: #f3f6f1; font-size: 24px; font-weight: 700; }
QPushButton { border: 1px solid #c5d0c7; border-radius: 8px; background: #ffffff; padding: 9px 16px; font-weight: 700; min-height: 18px; }
QPushButton:hover { background: #e2eae1; border-color: #91aa9d; }
QPushButton:pressed { background: #ceded3; }
QPushButton:focus { border: 2px solid #175e4b; padding: 8px 15px; }
QPushButton:disabled { color: #718078; background: #e8ece6; border-color: #d6ded6; }
QPushButton#primary { background: #175e4b; color: #ffffff; border: 1px solid #175e4b; }
QPushButton#primary:hover { background: #104b3b; }
QPushButton#primary:disabled { background: #d5dfd8; color: #64786c; border-color: #d5dfd8; }
QPushButton#recordLive[recording="true"] { background: #a13e34; color: #ffffff; border-color: #a13e34; }
QPushButton#recordLive[recording="true"]:disabled { background: #e8ece6; color: #718078; border-color: #d6ded6; }
QPushButton#tab { background: transparent; border: 1px solid transparent; color: #50645c; }
QPushButton#tab:checked { background: #dae9e0; color: #175e4b; border-color: #bfd4c5; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 13px 14px; margin: 3px 0; border-radius: 8px; border: 1px solid transparent; }
QListWidget::item:selected { background: #d5e3d7; color: #192c27; border: 1px solid #aec7b7; }
QListWidget::item:hover { background: #dde5dc; }
QListWidget:focus { border: 1px solid #175e4b; border-radius: 8px; }
QTableWidget { background: #ffffff; border: 1px solid #d6ded6; border-radius: 8px; gridline-color: transparent; selection-background-color: #dae9e0; selection-color: #192c27; }
QTableWidget::item { padding: 8px; border: none; }
QTableWidget::item:selected { background: #dae9e0; color: #192c27; }
QHeaderView::section { background: #edf1eb; color: #50645c; padding: 9px 8px; border: none; font-size: 12px; font-weight: 700; }
QLineEdit, QComboBox, QDateEdit { background: #ffffff; border: 1px solid #c5d0c7; border-radius: 8px; padding: 9px 12px; min-height: 18px; selection-background-color: #175e4b; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border: 2px solid #175e4b; padding: 8px 11px; }
QLineEdit:disabled, QComboBox:disabled { background: #e8ece6; color: #718078; }
QComboBox::drop-down, QDateEdit::drop-down { width: 24px; border: none; }
QComboBox { combobox-popup: 0; }
QComboBox QAbstractItemView { background: #ffffff; color: #192c27; border: 1px solid #c5d0c7; selection-background-color: #dae9e0; selection-color: #192c27; outline: 0; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 4px 10px; color: #192c27; background: #ffffff; }
QComboBox QAbstractItemView::item:selected { background: #dae9e0; color: #192c27; }
QComboBox QAbstractItemView::item:disabled { color: #718078; background: #e8ece6; }
QCalendarWidget { background: #ffffff; }
QProgressBar { background: #dbe3d9; border: none; border-radius: 3px; height: 6px; color: transparent; }
QProgressBar::chunk { background: #175e4b; border-radius: 3px; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #d6ded6; }
QSlider::sub-page:horizontal { background: #175e4b; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0; background: #175e4b; border-radius: 6px; }
QSplitter::handle { background: #d6ded6; width: 1px; margin: 20px 8px; }
QScrollBar:vertical { width: 10px; background: #edf1eb; border: none; }
QScrollBar::handle:vertical { background: #a9bbac; min-height: 24px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #192c27; color: #ffffff; border: none; padding: 6px; }
'''
