import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QWidget, QPushButton, QLineEdit, QComboBox,
                             QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QMessageBox, QFileDialog,
                             QDialog, QDoubleSpinBox, QTextEdit, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QScrollArea)
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
import arduino_cmds
import autoport
import time

# Josh Scheel -- joshua@e-scheel.com


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pump GUI")
        self.setGeometry(700, 200, 680, 950)

        # Scrollable central area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)
        central_widget = QWidget()
        scroll.setWidget(central_widget)

        self.layout = QGridLayout()
        central_widget.setLayout(self.layout)

        # --- Pump variables ---
        self.connected = False
        self.some_connected = False
        self.current_flowrate = 0  # uL/min
        self.arduino_cmds = arduino_cmds.PumpFluidics()
        self.is_on = False
        self.fwd = False
        self.paused = False

        # --- Pump selection variables ---
        self.current_serial = ''
        self.pump_serial_dict = {'Pump 0': None}
        self.current_index = 0
        self.connected_boards = {}
        self.current_board = None

        # --- Text file variables ---
        self.fname = "No file selected"
        self.current_file_tracker = 0
        self.text_file_count = 0
        self.text_file_list = []
        self.scheduled_commands = []
        self.original_commands = []   # (delay, command, serial) for restart
        self.worker_running = False
        self.worker = None
        self.thread = None

        #####################################################################################################################
        # UI ROWS
        #####################################################################################################################

        row = 0

        # --- Row 0: Pump image ---
        pixmap_path = os.path.join(os.path.dirname(__file__), "pump_render.png")
        pixmap = QPixmap(pixmap_path)
        scaled_pixmap = pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label = QLabel()
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.setFixedSize(scaled_pixmap.size())
        self.image_label.setStyleSheet("QLabel {border: 2px solid black;}")
        self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.layout.addWidget(self.image_label, row, 0, alignment=Qt.AlignTop | Qt.AlignHCenter)
        row += 1

        # --- Row 1: Multi pump connect ---
        self.multi_button_group_box = QGroupBox()
        self.multi_button_layout = QHBoxLayout()
        self.multi_button_group_box.setMinimumSize(300, 50)
        self.multi_button_label = QLabel("Connect multiple pumps:")
        font = self.multi_button_label.font()
        font.setBold(True)
        self.multi_button_label.setFont(font)
        self.multi_button_layout.addWidget(self.multi_button_label)
        self.multi_pump_edit = QLineEdit()
        self.multi_pump_edit.setPlaceholderText('Enter int (1 - 10)')
        self.multi_pump_edit.returnPressed.connect(lambda: self.multi_pump_connect(self.multi_pump_edit.text()))
        self.multi_button_layout.addWidget(self.multi_pump_edit)
        self.multi_button_group_box.setLayout(self.multi_button_layout)
        self.layout.addWidget(self.multi_button_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 2: Connect / Serial ---
        self.connect_button_group_box = QGroupBox()
        self.connect_button_layout = QHBoxLayout()
        self.connect_button_group_box.setMinimumSize(300, 50)
        self.new_pump_dropdown = QComboBox()
        self.new_pump_dropdown.addItems(["Pump 0"])
        self.new_pump_dropdown.currentTextChanged.connect(self.new_pump_dropdown_change)
        self.connect_button_layout.addWidget(self.new_pump_dropdown)
        self.connect_button_label = QLabel("Connect:")
        font = self.connect_button_label.font()
        font.setBold(True)
        self.connect_button_label.setFont(font)
        self.connect_button_layout.addWidget(self.connect_button_label)
        self.connect_button = QPushButton('Auto Connect')
        self.connect_button.setCheckable(True)
        self.connect_button.clicked.connect(lambda: self.connect_button_clicked())
        self.connect_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.connect_button_layout.addWidget(self.connect_button)
        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText('Enter Serial # or /dev/cu.*')
        self.serial_edit.returnPressed.connect(lambda: self.connect_serial(self.serial_edit.text()))
        self.connect_button_layout.addWidget(self.serial_edit)
        self.connect_button_group_box.setLayout(self.connect_button_layout)
        self.layout.addWidget(self.connect_button_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 3: Flowrate quick adjust ---
        self.flowrate_group_box = QGroupBox()
        self.flowrate_button_layout = QHBoxLayout()
        self.flowrate_group_box.setMinimumSize(450, 50)
        self.flowrate_button_label = QLabel("Enter flowrate:")
        font = self.flowrate_button_label.font()
        font.setBold(True)
        self.flowrate_button_label.setFont(font)
        self.flowrate_button_layout.addWidget(self.flowrate_button_label)
        self.flowrate_edit = QLineEdit()
        self.flowrate_edit.setPlaceholderText('Enter flow rate (uL/min)')
        self.flowrate_edit.returnPressed.connect(lambda: self.update_flowrate(self.flowrate_edit.text()))
        self.flowrate_button_layout.addWidget(self.flowrate_edit)
        self.current_flowrate_label = QLabel(f"Current flowrate: {self.current_flowrate} uL/min")
        font = self.current_flowrate_label.font()
        font.setBold(True)
        self.current_flowrate_label.setFont(font)
        self.flowrate_button_layout.addWidget(self.current_flowrate_label)
        self.flowrate_group_box.setLayout(self.flowrate_button_layout)
        self.layout.addWidget(self.flowrate_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 4: On/Off + Direction ---
        self.buttons_group_box = QGroupBox()
        self.buttons_layout = QHBoxLayout()
        self.buttons_group_box.setMinimumSize(450, 50)
        self.on_off_button = QPushButton('Pump: OFF')
        self.on_off_button.setCheckable(True)
        self.on_off_button.clicked.connect(lambda: self.on_off_button_clicked())
        self.on_off_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.buttons_layout.addWidget(self.on_off_button)
        self.direction_button = QPushButton('Direction: OFF')
        self.direction_button.clicked.connect(lambda: self.direction_button_clicked())
        self.direction_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.buttons_layout.addWidget(self.direction_button)
        self.buttons_group_box.setLayout(self.buttons_layout)
        self.layout.addWidget(self.buttons_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 5: Flow Behavior ---
        self.flow_group_box = QGroupBox("Flow Behavior")
        self.flow_group_layout = QGridLayout()
        self.flow_group_box.setFixedWidth(500)
        # Mode dropdown
        self.flow_behavior_dropdown = QComboBox()
        self.flow_behavior_dropdown.addItems(["Constant", "Pulse", "Oscillation", "Pulse of Oscillation"])
        self.flow_behavior_dropdown.currentTextChanged.connect(self.update_flow_param_visibility)
        self.flow_group_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.flow_group_layout.addWidget(self.flow_behavior_dropdown, 0, 1)
        # Apply button
        self.apply_flow_button = QPushButton("Apply Flow")
        self.apply_flow_button.clicked.connect(self.apply_flow_behavior)
        self.apply_flow_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
        self.flow_group_layout.addWidget(self.apply_flow_button, 0, 2, 1, 2)
        # Flow rate (all modes)
        self.flow_rate_param_label = QLabel("Flow Rate (uL/min):")
        self.flow_rate_param = QLineEdit()
        self.flow_rate_param.setPlaceholderText('uL/min')
        self.flow_group_layout.addWidget(self.flow_rate_param_label, 1, 0)
        self.flow_group_layout.addWidget(self.flow_rate_param, 1, 1)
        # Pulse freq
        self.pulse_freq_label = QLabel("Pulse Freq (Hz):")
        self.pulse_freq_param = QLineEdit()
        self.pulse_freq_param.setPlaceholderText('Hz')
        self.flow_group_layout.addWidget(self.pulse_freq_label, 1, 2)
        self.flow_group_layout.addWidget(self.pulse_freq_param, 1, 3)
        # Duty cycle
        self.duty_cycle_label = QLabel("Duty Cycle (0-1):")
        self.duty_cycle_param = QLineEdit()
        self.duty_cycle_param.setPlaceholderText('0.0 - 1.0')
        self.flow_group_layout.addWidget(self.duty_cycle_label, 2, 0)
        self.flow_group_layout.addWidget(self.duty_cycle_param, 2, 1)
        # Osc freq
        self.osc_freq_label = QLabel("Osc Freq (Hz):")
        self.osc_freq_param = QLineEdit()
        self.osc_freq_param.setPlaceholderText('Hz')
        self.flow_group_layout.addWidget(self.osc_freq_label, 2, 2)
        self.flow_group_layout.addWidget(self.osc_freq_param, 2, 3)
        # Osc amplitude
        self.osc_amp_label = QLabel("Osc Amplitude:")
        self.osc_amp_param = QLineEdit()
        self.osc_amp_param.setPlaceholderText('amplitude')
        self.flow_group_layout.addWidget(self.osc_amp_label, 3, 0)
        self.flow_group_layout.addWidget(self.osc_amp_param, 3, 1)

        self.flow_group_box.setLayout(self.flow_group_layout)
        self.layout.addWidget(self.flow_group_box, row, 0, alignment=Qt.AlignCenter)
        self.update_flow_param_visibility("Constant")
        row += 1

        # --- Row 6: Pause / Resume / Restart ---
        self.control_group_box = QGroupBox()
        self.control_layout = QHBoxLayout()
        self.control_group_box.setMinimumSize(450, 50)
        self.pause_button = QPushButton('Pause')
        self.pause_button.clicked.connect(self.pause_button_clicked)
        self.pause_button.setStyleSheet('background-color: #e6a817; color: white; padding: 5px;')
        self.control_layout.addWidget(self.pause_button)
        self.resume_button = QPushButton('Resume')
        self.resume_button.clicked.connect(self.resume_button_clicked)
        self.resume_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
        self.control_layout.addWidget(self.resume_button)
        self.restart_button = QPushButton('Restart Cycle')
        self.restart_button.clicked.connect(self.restart_cycle_button_clicked)
        self.restart_button.setStyleSheet('background-color: #3f7fbb; color: white; padding: 5px;')
        self.control_layout.addWidget(self.restart_button)
        self.control_group_box.setLayout(self.control_layout)
        self.layout.addWidget(self.control_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 7: File buttons ---
        self.text_file_buttons_group_box = QGroupBox()
        self.text_file_buttons_layout = QHBoxLayout()
        self.text_file_buttons_group_box.setMinimumSize(580, 50)
        self.create_experiment_button = QPushButton('Create Experiment')
        self.create_experiment_button.clicked.connect(self.open_create_experiment_dialog)
        self.create_experiment_button.setStyleSheet('background-color: #7b3fbb; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.create_experiment_button)
        self.upload_text_file_button = QPushButton('Upload .txt file')
        self.upload_text_file_button.clicked.connect(lambda: self.upload_text_file_button_clicked())
        self.upload_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.upload_text_file_button)
        self.change_text_file_button = QPushButton('Change current file')
        self.change_text_file_button.clicked.connect(lambda: self.change_text_file_button_clicked())
        self.change_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.change_text_file_button)
        self.run_text_file_button = QPushButton('Run .txt file')
        self.run_text_file_button.clicked.connect(lambda: self.run_text_file_button_clicked())
        self.run_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.run_text_file_button)
        self.exit_text_file_button = QPushButton('Exit current file')
        self.exit_text_file_button.clicked.connect(lambda: self.exit_text_file_button_clicked())
        self.exit_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.exit_text_file_button)
        self.text_file_buttons_group_box.setLayout(self.text_file_buttons_layout)
        self.layout.addWidget(self.text_file_buttons_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 8: File name labels ---
        self.text_file_names_group_box = QGroupBox()
        self.text_file_names_layout = QVBoxLayout()
        self.current_text_file_label = QLabel(f"Current .txt file: {self.fname}")
        self.text_file_names_layout.addWidget(self.current_text_file_label)
        self.text_file_names_group_box.setLayout(self.text_file_names_layout)
        self.layout.addWidget(self.text_file_names_group_box, row, 0, alignment=Qt.AlignCenter)
        row += 1

        # --- Row 9: Dynamic file display ---
        self.file_display_group = QGroupBox("File Contents")
        self.file_display_group.setFixedWidth(500)
        self.file_display_layout = QVBoxLayout()
        self.file_display = QTextEdit()
        self.file_display.setReadOnly(True)
        self.file_display.setMinimumHeight(150)
        self.file_display.setMaximumHeight(250)
        self.file_display.setPlaceholderText("No file loaded. Upload or create an experiment to see commands here.")
        self.file_display_layout.addWidget(self.file_display)
        self.file_display_group.setLayout(self.file_display_layout)
        self.layout.addWidget(self.file_display_group, row, 0, alignment=Qt.AlignCenter)
        row += 1

    #####################################################################################################################
    # Connection Functions
    #####################################################################################################################

    def multi_pump_connect(self, selected_text):
        self.multi_pump_edit.clear()
        self.multi_pump_window = self.SetMultiSerials(int(selected_text))
        self.multi_pump_window.data_emitted.connect(self.receive_data_from_child)
        self.multi_pump_window.show()

    def receive_data_from_child(self, received_data):
        print(f"Received data from child: {received_data}")
        self.pump_serial_dict = self.pump_serial_dict | received_data
        print(f'Pump Dict: {self.pump_serial_dict}')
        for i in received_data.keys():
            self.new_pump_dropdown.addItems([i])
        serials_to_connect = self.pump_serial_dict.values()
        self.connected_boards = self.connected_boards | autoport.connect_multiple(serials_to_connect)
        if self.connected_boards != {}:
            self.connect_button.setText("Status: >0 connections")
            self.connected = True
            self.connect_button.setChecked(True)
            self.connect_button.setStyleSheet('background-color: #d6bf16; color: white; padding: 5px;')
        print(f'here is self.connected_boards: {self.connected_boards}')

    def new_pump_dropdown_change(self, selected_text):
        try:
            self.current_board = self.connected_boards[self.pump_serial_dict[selected_text]]
            print(f'Connected to {selected_text} with serial {self.pump_serial_dict[selected_text]}')
            self.successful_connection()
            self.current_index = self.new_pump_dropdown.currentIndex()
        except:
            self.new_pump_dropdown.blockSignals(True)
            self.new_pump_dropdown.setCurrentIndex(self.current_index)
            self.new_pump_dropdown.blockSignals(False)
            QMessageBox.warning(self, 'No Connection to this pump',
                                'No device connected to this pump.\nPlease connect a device and try again.')

    def connect_button_clicked(self):
        if self.connected:
            QMessageBox.warning(self, 'Already Connected', 'Device already connected.')
            self.connect_button.setChecked(True)
            return
        try:
            self.current_board, self.new_board_dict = autoport.connect()
            self.connected_boards = self.connected_boards | self.new_board_dict
            self.successful_connection()
        except Exception as e:
            self.connect_button.setText("Status: Not Connected")
            self.connect_button.setStyleSheet('color: red;')

    def connect_serial(self, selected_text):
        if self.connected:
            QMessageBox.warning(self, 'Already Connected', 'Device already connected.')
            self.serial_edit.clear()
            return
        try:
            print(selected_text)
            self.current_board, self.new_board_dict = autoport.connect(SERIAL=selected_text)
            self.connected_boards = self.connected_boards | self.new_board_dict
            self.successful_connection()
        except Exception as e:
            self.connect_button.setText("Status: Not Connected")
            self.connect_button.setStyleSheet('color: red;')
            self.serial_edit.clear()

    def warn_no_connection(self):
        QMessageBox.warning(self, 'No Connection',
                            'No device connected. Please connect a device and try again.')

    def successful_connection(self):
        self.connect_button.setText("Status: Connected")
        self.connected = True
        self.connect_button.setChecked(True)
        self.connect_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
        self.is_on = False
        self.on_off_button.setChecked(True)
        self.on_off_button_clicked()
        self.current_flowrate = 1.5
        self.current_flowrate_label.setText(f'Current flowrate: {self.current_flowrate} uL/min')
        self.serial_edit.clear()

    #####################################################################################################################
    # Pump Control Functions
    #####################################################################################################################

    def on_off_button_clicked(self):
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            self.on_off_button.setChecked(False)
        elif not self.is_on:
            self.is_on = True
            self.current_board.sendcommand('123')
            self.on_off_button.setText('Pump: ON')
            self.on_off_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
            if not self.fwd:
                self.direction_button.setText('Direction: <--')
            elif self.fwd:
                self.direction_button.setText('Direction: -->')
        elif self.is_on:
            self.is_on = False
            self.current_board.sendcommand('0')
            self.on_off_button.setText('Pump: OFF')
            self.on_off_button.setStyleSheet('background-color: #bb3f3f; color: white; padding: 5px;')
            self.direction_button.setText('Direction: OFF')
            self.flow_behavior_dropdown.blockSignals(True)
            self.flow_behavior_dropdown.setCurrentIndex(0)
            self.flow_behavior_dropdown.blockSignals(False)

    def direction_button_clicked(self):
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            self.direction_button.setText('Direction: OFF')
        elif not self.is_on:
            self.direction_button.setText('Direction: OFF')
        elif not self.fwd:
            self.fwd = True
            self.current_board.sendcommand('321')
            self.direction_button.setText('Direction: -->')
        elif self.fwd:
            self.fwd = False
            self.current_board.sendcommand('321')
            self.direction_button.setText('Direction: <--')

    def update_flowrate(self, new_flowrate):
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            self.flowrate_edit.clear()
            return
        elif not self.is_on:
            self.flowrate_edit.clear()
            return
        try:
            self.current_flowrate = float(new_flowrate)
            if self.current_flowrate > 0:
                self.current_board.sendcommand(str(self.current_flowrate))
                self.current_flowrate_label.setText(f"Current flowrate: {self.current_flowrate} uL/min")
                print(f"Flowrate updated to: {self.current_flowrate}")
            else:
                raise ValueError("Flow rate must be greater than 0")
        except ValueError:
            print("Invalid flowrate entered. Please enter a number.")
        finally:
            self.flowrate_edit.clear()

    #####################################################################################################################
    # Flow Behavior Functions
    #####################################################################################################################

    def update_flow_param_visibility(self, mode):
        """Show/hide parameter fields based on selected flow behavior mode."""
        # Hide all optional params first
        for widget in [self.pulse_freq_param, self.pulse_freq_label,
                       self.duty_cycle_param, self.duty_cycle_label,
                       self.osc_freq_param, self.osc_freq_label,
                       self.osc_amp_param, self.osc_amp_label]:
            widget.hide()

        # Flow rate always visible
        self.flow_rate_param.show()
        self.flow_rate_param_label.show()

        if mode == "Constant":
            pass
        elif mode == "Pulse":
            self.pulse_freq_param.show()
            self.pulse_freq_label.show()
            self.duty_cycle_param.show()
            self.duty_cycle_label.show()
        elif mode == "Oscillation":
            self.osc_freq_param.show()
            self.osc_freq_label.show()
            self.osc_amp_param.show()
            self.osc_amp_label.show()
        elif mode == "Pulse of Oscillation":
            self.pulse_freq_param.show()
            self.pulse_freq_label.show()
            self.duty_cycle_param.show()
            self.duty_cycle_label.show()
            self.osc_freq_param.show()
            self.osc_freq_label.show()
            self.osc_amp_param.show()
            self.osc_amp_label.show()

    def apply_flow_behavior(self):
        """Build and send the flow behavior command to the Arduino."""
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            return
        if not self.is_on:
            QMessageBox.warning(self, 'Pump Off', 'Turn the pump on first.')
            return

        mode = self.flow_behavior_dropdown.currentText()
        try:
            rate = float(self.flow_rate_param.text())
            if rate <= 0:
                raise ValueError("Flow rate must be greater than 0")

            if mode == "Constant":
                cmd = f"FLOWA,{rate}"
            elif mode == "Pulse":
                duty = float(self.duty_cycle_param.text())
                freq = float(self.pulse_freq_param.text())
                cmd = f"FLOWB,{rate},{duty},{freq}"
            elif mode == "Oscillation":
                freq = float(self.osc_freq_param.text())
                amp = float(self.osc_amp_param.text())
                cmd = f"FLOWC,{rate},{freq},{amp}"
            elif mode == "Pulse of Oscillation":
                pfreq = float(self.pulse_freq_param.text())
                duty = float(self.duty_cycle_param.text())
                ofreq = float(self.osc_freq_param.text())
                oamp = float(self.osc_amp_param.text())
                cmd = f"FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"
            else:
                return

            self.current_board.sendcommand(cmd)
            self.current_flowrate = rate
            self.current_flowrate_label.setText(f"Current flowrate: {self.current_flowrate} uL/min")
            print(f"Flow command sent: {cmd}")

        except ValueError as e:
            QMessageBox.warning(self, 'Invalid Input', f'Please enter valid numbers.\n{str(e)}')

    #####################################################################################################################
    # Pause / Resume / Restart Functions
    #####################################################################################################################

    def pause_button_clicked(self):
        """Pause pump and freeze the command scheduler."""
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            return
        if not self.worker_running or self.worker is None:
            QMessageBox.warning(self, 'Nothing Running', 'No scheduled commands are running.')
            return
        if self.paused:
            return

        self.paused = True
        self.worker.pause()
        self.current_board.sendcommand('0')
        self.is_on = False
        self.on_off_button.setText('Pump: PAUSED')
        self.on_off_button.setStyleSheet('background-color: #e6a817; color: white; padding: 5px;')
        self.pause_button.setStyleSheet('background-color: #bb3f3f; color: white; padding: 5px;')
        print("Paused.")

    def resume_button_clicked(self):
        """Resume pump and continue the command scheduler."""
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            return
        if not self.paused:
            return

        self.paused = False
        self.current_board.sendcommand('123')
        self.is_on = True
        self.worker.resume()
        self.on_off_button.setText('Pump: ON')
        self.on_off_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
        self.pause_button.setStyleSheet('background-color: #e6a817; color: white; padding: 5px;')
        print("Resumed.")

    def restart_cycle_button_clicked(self):
        """Stop current execution and restart the schedule from the beginning."""
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            return
        if not self.original_commands:
            QMessageBox.warning(self, 'No Commands', 'No commands to restart.')
            return

        # Stop current worker
        try:
            if self.worker and self.thread and self.thread.isRunning():
                self.worker.stop()
                self.thread.quit()
                self.thread.wait()
        except RuntimeError:
            pass

        self.paused = False
        self.worker_running = False
        self.pause_button.setStyleSheet('background-color: #e6a817; color: white; padding: 5px;')

        # Rebuild scheduled commands from original delays
        now = time.monotonic()
        new_commands = []
        for delay, command, serial in self.original_commands:
            execute_time = now + delay
            if serial in self.connected_boards:
                board = self.connected_boards[serial]
            else:
                unique_boards = list({id(b): b for b in self.connected_boards.values()}.values())
                if len(unique_boards) == 1:
                    board = unique_boards[0]
                else:
                    continue
            new_commands.append((execute_time, command, board))

        new_commands.sort(key=lambda x: x[0])
        self.scheduled_commands = new_commands

        # Start new worker
        self.thread = QThread()
        self.worker = self.CommandRunner(self.scheduled_commands, self)
        self.worker.moveToThread(self.thread)
        self.worker.log.connect(self.handle_log)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.worker.close_worker)
        self.thread.start()
        self.worker_running = True
        print("Cycle restarted.")

    #####################################################################################################################
    # Text File Functions
    #####################################################################################################################

    def upload_text_file_button_clicked(self):
        self.fname, _ = QFileDialog.getOpenFileName(self, "Open File", "", ".txt Files (*.txt)")
        if self.fname:
            self.selected_file = self.fname
            self.current_text_file_label.setText(f"Current File Selected: {self.fname}")
            self.current_file_tracker = 0
            self.text_file_count += 1
            self.text_file_list.append(self.fname)
            new_label = QLabel(f"{self.text_file_count}. {self.fname[-15:]}")
            self.text_file_names_layout.addWidget(new_label)
            self.display_file_contents(self.fname)

    def change_text_file_button_clicked(self):
        if self.text_file_count >= 1:
            self.current_text_file_label.setText(
                f"Current File Selected: {self.text_file_list[self.current_file_tracker]}")
            self.fname = self.text_file_list[self.current_file_tracker]
            self.current_file_tracker += 1
            if self.current_file_tracker == len(self.text_file_list):
                self.current_file_tracker = 0
            self.display_file_contents(self.fname)

    def display_file_contents(self, filepath):
        """Parse and display file contents in a readable format."""
        try:
            with open(filepath, 'r') as f:
                raw_data = " ".join(f.readlines())

            entries = raw_data.split("%%%%%%%%%")
            display_lines = []
            step = 1

            for entry in entries:
                if "*********" in entry and "#########" in entry:
                    try:
                        serial_part, rest = entry.split("*********")
                        command_part, time_part = rest.split("#########")
                        serial = serial_part.strip()
                        command = command_part.strip()
                        delay = time_part.strip()
                        readable = self._decode_command(command)
                        serial_short = serial[-8:] if len(serial) > 8 else serial
                        display_lines.append(
                            f"Step {step}:  [{delay}s]  {readable}   (pump: {serial_short})")
                        step += 1
                    except ValueError:
                        continue

            if display_lines:
                self.file_display.setText("\n".join(display_lines))
            else:
                self.file_display.setText("File loaded but no valid commands found.")

        except Exception as e:
            self.file_display.setText(f"Error reading file: {str(e)}")

    def _decode_command(self, command):
        """Convert a command string to a human-readable description."""
        if command == '123':
            return 'Turn ON'
        elif command == '0':
            return 'Turn OFF'
        elif command == '321':
            return 'Toggle Direction'
        elif command.startswith('FLOWA'):
            parts = command.split(',')
            rate = parts[1] if len(parts) > 1 else '?'
            return f'Constant Flow @ {rate} uL/min'
        elif command.startswith('FLOWB'):
            parts = command.split(',')
            rate = parts[1] if len(parts) > 1 else '?'
            duty = parts[2] if len(parts) > 2 else '?'
            freq = parts[3] if len(parts) > 3 else '?'
            return f'Pulse @ {rate} uL/min, duty={duty}, freq={freq} Hz'
        elif command.startswith('FLOWC'):
            parts = command.split(',')
            rate = parts[1] if len(parts) > 1 else '?'
            freq = parts[2] if len(parts) > 2 else '?'
            amp = parts[3] if len(parts) > 3 else '?'
            return f'Oscillation @ {rate} uL/min, freq={freq} Hz, amp={amp}'
        elif command.startswith('FLOWD'):
            parts = command.split(',')
            rate = parts[1] if len(parts) > 1 else '?'
            pf = parts[2] if len(parts) > 2 else '?'
            duty = parts[3] if len(parts) > 3 else '?'
            oa = parts[4] if len(parts) > 4 else '?'
            of_ = parts[5] if len(parts) > 5 else '?'
            return f'Pulse of Osc @ {rate} uL/min, pFreq={pf}, duty={duty}, oAmp={oa}, oFreq={of_}'
        else:
            try:
                float(command)
                return f'Set Flow Rate: {command} uL/min'
            except ValueError:
                return f'Command: {command}'

    def run_text_file_button_clicked(self):
        if not hasattr(self, 'fname') or not self.fname or self.fname == "No file selected":
            QMessageBox.warning(self, "No File", "Please select a text file first.")
            return
        if self.connected_boards == {}:
            QMessageBox.warning(self, "No Boards Connected", "Please connect a board first.")
            return

        now = time.monotonic()
        new_commands = []
        new_originals = []

        try:
            with open(self.fname, 'r') as file:
                raw_data = " ".join(file.readlines())
                command_entries = raw_data.split("%%%%%%%%%")

                for entry in command_entries:
                    if "*********" in entry and "#########" in entry:
                        try:
                            serial_part, rest = entry.split("*********")
                            command_part, time_part = rest.split("#########")

                            serial = serial_part.strip()
                            command = command_part.strip()
                            delay = float(time_part.strip())
                            execute_time = now + delay

                            # Store original for restart
                            new_originals.append((delay, command, serial))

                            # Validate board exists
                            if serial in self.connected_boards:
                                board = self.connected_boards[serial]
                                new_commands.append((execute_time, command, board))
                            else:
                                unique_boards = list(
                                    {id(b): b for b in self.connected_boards.values()}.values())
                                if len(unique_boards) == 1:
                                    board = unique_boards[0]
                                    print(
                                        f"Unknown serial: {serial}. "
                                        f"Falling back to the only connected board.")
                                    new_commands.append((execute_time, command, board))
                                else:
                                    print(
                                        f"Unknown serial: {serial}, skipping command. "
                                        f"Known keys: {list(self.connected_boards.keys())}")
                                    continue

                        except ValueError as e:
                            print(f"Malformed entry: {entry} -- {e}")
                            continue

            # Sort by execution time
            new_commands.sort(key=lambda x: x[0])
            new_originals.sort(key=lambda x: x[0])

            if self.worker_running:
                self.scheduled_commands += new_commands
                self.scheduled_commands.sort(key=lambda x: x[0])
                self.original_commands += new_originals
                self.original_commands.sort(key=lambda x: x[0])
                print('command worker is already running')
            elif not self.worker_running:
                self.scheduled_commands = new_commands
                self.original_commands = new_originals

                # Start worker
                self.thread = QThread()
                self.worker = self.CommandRunner(self.scheduled_commands, self)
                self.worker.moveToThread(self.thread)
                self.worker.log.connect(self.handle_log)
                self.thread.started.connect(self.worker.run)
                self.worker.finished.connect(self.thread.quit)
                self.worker.finished.connect(self.worker.deleteLater)
                self.thread.finished.connect(self.thread.deleteLater)
                self.worker.finished.connect(self.worker.close_worker)
                self.thread.start()
                self.worker_running = True

        except Exception as e:
            print('file error')
            QMessageBox.critical(self, "File Error", f"Error reading the file:\n{str(e)}")

    def handle_log(self, emission):
        info = emission.split('*********')
        board = info[0]
        command = info[1]

        if command == '123':
            self.is_on = True
            self.on_off_button.setChecked(True)
            self.on_off_button.setText('Pump: ON')
            self.on_off_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
            self.direction_button.setText('Direction: -->' if self.fwd else 'Direction: <--')
        elif command == '0':
            self.is_on = False
            self.on_off_button.setChecked(False)
            self.on_off_button.setText('Pump: OFF')
            self.on_off_button.setStyleSheet('background-color: #bb3f3f; color: white; padding: 5px;')
            self.direction_button.setText('Direction: OFF')
            self.flow_behavior_dropdown.blockSignals(True)
            self.flow_behavior_dropdown.setCurrentIndex(0)
            self.flow_behavior_dropdown.blockSignals(False)
        elif command == '321':
            self.fwd = not self.fwd
            self.direction_button.setText('Direction: -->' if self.fwd else 'Direction: <--')
        elif command.startswith('FLOW'):
            self.flow_behavior_dropdown.blockSignals(True)
            if command.startswith('FLOWA'):
                self.flow_behavior_dropdown.setCurrentIndex(0)
            elif command.startswith('FLOWB'):
                self.flow_behavior_dropdown.setCurrentIndex(1)
            elif command.startswith('FLOWC'):
                self.flow_behavior_dropdown.setCurrentIndex(2)
            elif command.startswith('FLOWD'):
                self.flow_behavior_dropdown.setCurrentIndex(3)
            self.flow_behavior_dropdown.blockSignals(False)
            # Update flow rate from command params
            parts = command.split(',')
            if len(parts) > 1:
                try:
                    rate = float(parts[1])
                    self.current_flowrate = rate
                    self.current_flowrate_label.setText(f"Current flowrate: {self.current_flowrate} uL/min")
                except ValueError:
                    pass
        else:
            try:
                self.current_flowrate = float(command)
                if self.current_flowrate > 0:
                    self.current_flowrate_label.setText(f"Current flowrate: {self.current_flowrate} uL/min")
                    print(f"Flowrate updated to: {self.current_flowrate}")
                else:
                    raise ValueError("Flow rate must be greater than 0")
            except ValueError:
                print("Invalid flowrate entered. Please enter a number.")

    def exit_text_file_button_clicked(self):
        if not self.connected or self.current_board is None:
            self.warn_no_connection()
            return
        try:
            running = self.worker and self.thread and self.thread.isRunning()
        except RuntimeError:
            running = False
        if running:
            self.worker.stop()
            self.thread.quit()
            self.scheduled_commands = []
            self.original_commands = []
            self.worker_running = False
            self.paused = False
            self.is_on = True
            self.on_off_button_clicked()
            self.on_off_button.setChecked(False)
            self.pause_button.setStyleSheet('background-color: #e6a817; color: white; padding: 5px;')
            print('Thread Exited.')

    #####################################################################################################################
    # Create Experiment Dialog
    #####################################################################################################################

    def open_create_experiment_dialog(self):
        dialog = self.CreateExperimentDialog(self.connected_boards, self.pump_serial_dict, self)
        dialog.file_generated.connect(self._on_experiment_file_generated)
        dialog.exec_()

    def _on_experiment_file_generated(self, filepath, display_text):
        """Handle the generated experiment file."""
        self.fname = filepath
        self.current_text_file_label.setText(f"Current File Selected: {filepath}")
        self.text_file_count += 1
        self.text_file_list.append(filepath)
        new_label = QLabel(f"{self.text_file_count}. {os.path.basename(filepath)}")
        self.text_file_names_layout.addWidget(new_label)
        self.file_display.setText(display_text)

    #####################################################################################################################
    # CommandRunner sub-class (with pause/resume)
    #####################################################################################################################

    class CommandRunner(QObject):
        finished = pyqtSignal()
        log = pyqtSignal(str)

        def __init__(self, scheduled_commands, main_window):
            super().__init__()
            self.scheduled_commands = scheduled_commands
            self._is_running = True
            self._is_paused = False
            self._pause_start = 0
            self._command_index = 0
            self.main_window = main_window

        def run(self):
            try:
                for i in range(len(self.scheduled_commands)):
                    self._command_index = i

                    while self._is_running:
                        # If paused, just sleep until unpaused
                        if self._is_paused:
                            time.sleep(0.1)
                            continue

                        # Re-read execute_time (may have been shifted by resume)
                        execute_time = self.scheduled_commands[i][0]
                        wait_time = execute_time - time.monotonic()
                        if wait_time <= 0:
                            break
                        time.sleep(min(wait_time, 0.1))

                    if not self._is_running:
                        break

                    _, command, board = self.scheduled_commands[i]
                    self.log.emit(f"{board}*********{command}")
                    self.main_window.current_board = board
                    self.execute_command(command, board)

            finally:
                self.finished.emit()

        def execute_command(self, command, board):
            board.sendcommand(str(command))

        def pause(self):
            self._is_paused = True
            self._pause_start = time.monotonic()

        def resume(self):
            if self._is_paused:
                pause_duration = time.monotonic() - self._pause_start
                # Shift all remaining command times forward
                for i in range(self._command_index, len(self.scheduled_commands)):
                    t, cmd, brd = self.scheduled_commands[i]
                    self.scheduled_commands[i] = (t + pause_duration, cmd, brd)
                self._is_paused = False

        def stop(self):
            self._is_running = False

        def close_worker(self):
            print('close worker called')
            self.main_window.worker_running = False

    #####################################################################################################################
    # SetMultiSerials sub-class
    #####################################################################################################################

    class SetMultiSerials(QWidget):
        data_emitted = pyqtSignal(dict)

        def __init__(self, num_pumps):
            super().__init__()
            self.setWindowTitle("Set pump serials")
            self.setGeometry(200, 200, 300, 200)
            self.layout = QGridLayout()
            self.setLayout(self.layout)
            self.line_edits = []
            self.serial_dict = {}

            if num_pumps > 10:
                num_pumps = 10

            for i in range(num_pumps):
                line_edit = QLineEdit()
                line_edit.setPlaceholderText(f'Enter Pump {i + 1} serial #')
                self.layout.addWidget(line_edit)
                self.line_edits.append(line_edit)

            self.button = QPushButton("Collect Serial #s")
            self.button.clicked.connect(self.collect_serials)
            self.layout.addWidget(self.button)

        def collect_serials(self):
            for i, line_edit in enumerate(self.line_edits):
                self.serial_dict[f'Pump {i + 1}'] = line_edit.text()
            self.data_emitted.emit(self.serial_dict)
            self.close()

    #####################################################################################################################
    # CreateExperimentDialog sub-class
    #####################################################################################################################

    class CreateExperimentDialog(QDialog):
        file_generated = pyqtSignal(str, str)  # filepath, display_text

        def __init__(self, connected_boards, pump_serial_dict, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Create Experiment")
            self.setGeometry(300, 200, 780, 600)
            self.connected_boards = connected_boards
            self.pump_serial_dict = pump_serial_dict
            self.steps = []

            layout = QVBoxLayout()
            self.setLayout(layout)

            # --- Input Section ---
            input_group = QGroupBox("Add Step")
            input_layout = QGridLayout()

            # Pump selector
            self.pump_combo = QComboBox()
            pump_names = list(pump_serial_dict.keys())
            self.pump_combo.addItems(pump_names)
            input_layout.addWidget(QLabel("Pump:"), 0, 0)
            input_layout.addWidget(self.pump_combo, 0, 1)

            # Time input
            self.time_input = QDoubleSpinBox()
            self.time_input.setRange(0, 999999)
            self.time_input.setDecimals(2)
            self.time_input.setSuffix(" s")
            input_layout.addWidget(QLabel("Time (s from start):"), 0, 2)
            input_layout.addWidget(self.time_input, 0, 3)

            # Behavior selector
            self.behavior_combo = QComboBox()
            self.behavior_combo.addItems([
                "Turn On", "Turn Off", "Change Direction",
                "Constant", "Pulse", "Oscillation", "Pulse of Oscillation"
            ])
            self.behavior_combo.currentTextChanged.connect(self._update_param_visibility)
            input_layout.addWidget(QLabel("Behavior:"), 1, 0)
            input_layout.addWidget(self.behavior_combo, 1, 1, 1, 3)

            # --- Parameter inputs ---
            self.rate_label = QLabel("Flow Rate (uL/min):")
            self.rate_input = QDoubleSpinBox()
            self.rate_input.setRange(0.01, 10000)
            self.rate_input.setDecimals(2)
            input_layout.addWidget(self.rate_label, 2, 0)
            input_layout.addWidget(self.rate_input, 2, 1)

            self.pulse_freq_label = QLabel("Pulse Freq (Hz):")
            self.pulse_freq_input = QDoubleSpinBox()
            self.pulse_freq_input.setRange(0.001, 1000)
            self.pulse_freq_input.setDecimals(3)
            input_layout.addWidget(self.pulse_freq_label, 2, 2)
            input_layout.addWidget(self.pulse_freq_input, 2, 3)

            self.duty_label = QLabel("Duty Cycle (0-1):")
            self.duty_input = QDoubleSpinBox()
            self.duty_input.setRange(0, 1)
            self.duty_input.setDecimals(2)
            self.duty_input.setSingleStep(0.05)
            input_layout.addWidget(self.duty_label, 3, 0)
            input_layout.addWidget(self.duty_input, 3, 1)

            self.osc_freq_label = QLabel("Osc Freq (Hz):")
            self.osc_freq_input = QDoubleSpinBox()
            self.osc_freq_input.setRange(0.001, 1000)
            self.osc_freq_input.setDecimals(3)
            input_layout.addWidget(self.osc_freq_label, 3, 2)
            input_layout.addWidget(self.osc_freq_input, 3, 3)

            self.osc_amp_label = QLabel("Osc Amplitude:")
            self.osc_amp_input = QDoubleSpinBox()
            self.osc_amp_input.setRange(0, 10000)
            self.osc_amp_input.setDecimals(2)
            input_layout.addWidget(self.osc_amp_label, 4, 0)
            input_layout.addWidget(self.osc_amp_input, 4, 1)

            # Add step button
            self.add_step_btn = QPushButton("Add Step")
            self.add_step_btn.clicked.connect(self._add_step)
            self.add_step_btn.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
            input_layout.addWidget(self.add_step_btn, 4, 2, 1, 2)

            input_group.setLayout(input_layout)
            layout.addWidget(input_group)

            # --- Steps Table ---
            self.steps_table = QTableWidget()
            self.steps_table.setColumnCount(5)
            self.steps_table.setHorizontalHeaderLabels(
                ["Pump", "Time (s)", "Behavior", "Command", "Description"])
            self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.steps_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            layout.addWidget(self.steps_table)

            # --- Bottom Buttons ---
            btn_layout = QHBoxLayout()

            self.remove_btn = QPushButton("Remove Selected")
            self.remove_btn.clicked.connect(self._remove_step)
            self.remove_btn.setStyleSheet('background-color: #bb3f3f; color: white; padding: 5px;')
            btn_layout.addWidget(self.remove_btn)

            self.generate_btn = QPushButton("Generate & Save File")
            self.generate_btn.clicked.connect(self._generate_file)
            self.generate_btn.setStyleSheet('background-color: #7b3fbb; color: white; padding: 8px;')
            btn_layout.addWidget(self.generate_btn)

            layout.addLayout(btn_layout)

            # Init visibility
            self._update_param_visibility("Turn On")

        def _update_param_visibility(self, mode):
            """Show/hide parameter fields based on selected behavior."""
            for w in [self.rate_input, self.rate_label,
                      self.pulse_freq_input, self.pulse_freq_label,
                      self.duty_input, self.duty_label,
                      self.osc_freq_input, self.osc_freq_label,
                      self.osc_amp_input, self.osc_amp_label]:
                w.hide()

            if mode in ("Constant", "Pulse", "Oscillation", "Pulse of Oscillation"):
                self.rate_input.show()
                self.rate_label.show()
            if mode in ("Pulse", "Pulse of Oscillation"):
                self.pulse_freq_input.show()
                self.pulse_freq_label.show()
                self.duty_input.show()
                self.duty_label.show()
            if mode in ("Oscillation", "Pulse of Oscillation"):
                self.osc_freq_input.show()
                self.osc_freq_label.show()
                self.osc_amp_input.show()
                self.osc_amp_label.show()

        def _build_command(self, mode):
            """Build command string and human-readable description for the given mode."""
            if mode == "Turn On":
                return "123", "Turn ON"
            elif mode == "Turn Off":
                return "0", "Turn OFF"
            elif mode == "Change Direction":
                return "321", "Toggle Direction"
            elif mode == "Constant":
                rate = self.rate_input.value()
                return f"FLOWA,{rate}", f"Constant @ {rate} uL/min"
            elif mode == "Pulse":
                rate = self.rate_input.value()
                duty = self.duty_input.value()
                freq = self.pulse_freq_input.value()
                return (f"FLOWB,{rate},{duty},{freq}",
                        f"Pulse @ {rate} uL/min, duty={duty}, freq={freq} Hz")
            elif mode == "Oscillation":
                rate = self.rate_input.value()
                freq = self.osc_freq_input.value()
                amp = self.osc_amp_input.value()
                return (f"FLOWC,{rate},{freq},{amp}",
                        f"Oscillation @ {rate} uL/min, freq={freq} Hz, amp={amp}")
            elif mode == "Pulse of Oscillation":
                rate = self.rate_input.value()
                pf = self.pulse_freq_input.value()
                duty = self.duty_input.value()
                oa = self.osc_amp_input.value()
                of_ = self.osc_freq_input.value()
                return (f"FLOWD,{rate},{pf},{duty},{oa},{of_}",
                        f"Pulse of Osc @ {rate} uL/min, pFreq={pf}, duty={duty}, oAmp={oa}, oFreq={of_}")
            return "", ""

        def _add_step(self):
            pump_name = self.pump_combo.currentText()
            time_val = self.time_input.value()
            mode = self.behavior_combo.currentText()
            command, description = self._build_command(mode)

            serial = self.pump_serial_dict.get(pump_name)
            serial_str = str(serial) if serial else pump_name

            self.steps.append({
                'pump': pump_name,
                'serial': serial_str,
                'time': time_val,
                'mode': mode,
                'command': command,
                'description': description
            })

            # Add to table
            table_row = self.steps_table.rowCount()
            self.steps_table.insertRow(table_row)
            self.steps_table.setItem(table_row, 0, QTableWidgetItem(pump_name))
            self.steps_table.setItem(table_row, 1, QTableWidgetItem(f"{time_val:.2f}"))
            self.steps_table.setItem(table_row, 2, QTableWidgetItem(mode))
            self.steps_table.setItem(table_row, 3, QTableWidgetItem(command))
            self.steps_table.setItem(table_row, 4, QTableWidgetItem(description))

        def _remove_step(self):
            selected = self.steps_table.currentRow()
            if selected >= 0:
                self.steps_table.removeRow(selected)
                self.steps.pop(selected)

        def _generate_file(self):
            if not self.steps:
                QMessageBox.warning(self, "No Steps", "Add at least one step before generating.")
                return

            # Ask where to save
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Save Experiment File", "", ".txt Files (*.txt)")
            if not filepath:
                return

            # Sort steps by time
            sorted_steps = sorted(self.steps, key=lambda s: s['time'])

            # Build file content and display text
            file_parts = []
            display_lines = []
            for i, step in enumerate(sorted_steps):
                serial = step['serial']
                file_parts.append(
                    f"{serial}*********{step['command']}#########{step['time']}")
                display_lines.append(
                    f"Step {i + 1}:  [{step['time']:.2f}s]  {step['description']}   "
                    f"(pump: {step['pump']})")

            file_content = "%%%%%%%%%".join(file_parts)
            display_text = "\n".join(display_lines)

            # Write file
            with open(filepath, 'w') as f:
                f.write(file_content)

            print(f"Experiment file saved: {filepath}")
            self.file_generated.emit(filepath, display_text)
            self.accept()
