import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QWidget, QPushButton, QLineEdit,QComboBox,
                             QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,QMessageBox,QFileDialog)
from PyQt5.QtGui import QIcon, QFont, QPixmap
from PyQt5.QtCore import Qt,QObject, QThread, pyqtSignal
import arduino_cmds
import autoport
import time
import re

# Josh Scheel -- joshua@e-scheel.com


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Title and size
        self.setWindowTitle("Pump GUI") # Title
        self.setGeometry(700,300,500,500) # Window location and size

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Layout
        self.layout = QGridLayout()
        central_widget.setLayout(self.layout)

        # Pump variables
        self.connected = False
        self.some_connected = False
        self.current_flowrate = 0 #µL/min (max of 40)
        self.arduino_cmds = arduino_cmds.PumpFluidics()
        self.is_on = False
        self.fwd = False # Need to fix later to read fwd from arduino

        # Pump selection variables
        self.current_serial = ''
        self.pump_serial_dict = {'Pump 0': None}
        self.current_index = 0
        self.connected_boards = {}
        self.current_board = None

        # Text File variables
        self.fname = "No file selected"
        self.current_file_tracker = 0
        self.text_file_count = 0
        self.text_file_list = []
        self.scheduled_commands = []
        #self.worker.log.connect(self.handle_log)
        self.worker_running = False



        #####################################################################################################################
        # Class Labels, Buttons, and other widgets
        #####################################################################################################################

        # Pump Rendering
        pixmap_path = os.path.join(os.path.dirname(__file__), "pump_render.png")
        pixmap = QPixmap(pixmap_path)
        scaled_pixmap = pixmap.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label = QLabel()
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.setFixedSize(scaled_pixmap.size())
        self.image_label.setStyleSheet("""QLabel {border: 2px solid black;}""")
        self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.layout.addWidget(self.image_label, 0, 0, alignment=Qt.AlignTop | Qt.AlignHCenter)

        # 1st row - Set up multiple pumps 

        self.multi_button_group_box = QGroupBox()
        self.multi_button_layout = QHBoxLayout()
        self.multi_button_group_box.setMinimumSize(300, 50)
        # Instruction label
        self.multi_button_label = QLabel("Connect multiple pumps:")
        self.font = self.multi_button_label.font()
        self.font.setBold(True)
        self.multi_button_label.setFont(self.font)
        self.multi_button_layout.addWidget(self.multi_button_label)
        # Multi pump line edit
        self.multi_pump_edit = QLineEdit()
        self.multi_pump_edit.setPlaceholderText('Enter int (1 - 10)')
        self.multi_pump_edit.returnPressed.connect(lambda: self.multi_pump_connect(self.multi_pump_edit.text()))
        self.multi_button_layout.addWidget(self.multi_pump_edit)
         # Add to main layout
        self.multi_button_group_box.setLayout(self.multi_button_layout)
        self.layout.addWidget(self.multi_button_group_box, 1, 0, alignment=Qt.AlignCenter)

        # 2nd row - Button

        self.connect_button_group_box = QGroupBox()
        self.connect_button_layout = QHBoxLayout()
        self.connect_button_group_box.setMinimumSize(300, 50)
        # New pump button
        self.new_pump_dropdown = QComboBox()
        self.new_pump_dropdown.addItems(["Pump 0"]) # Replace with pump names
        self.new_pump_dropdown.currentTextChanged.connect(self.new_pump_dropdown_change)
        self.connect_button_layout.addWidget(self.new_pump_dropdown)
        # Connect Label
        self.connect_button_label = QLabel("Connect:")
        self.font = self.connect_button_label.font()
        self.font.setBold(True)
        self.connect_button_label.setFont(self.font)
        self.connect_button_layout.addWidget(self.connect_button_label)
        # Connect Button
        self.connect_button = QPushButton('Auto Connect')
        self.connect_button.setCheckable(True)
        self.connect_button.clicked.connect(lambda: self.connect_button_clicked())
        self.connect_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.connect_button_layout.addWidget(self.connect_button)
        # Manual Serial number line edit
        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText('Enter Serial # or /dev/cu.*')
        self.serial_edit.returnPressed.connect(lambda: self.connect_serial(self.serial_edit.text()))
        self.connect_button_layout.addWidget(self.serial_edit)
        # Add to main layout
        self.connect_button_group_box.setLayout(self.connect_button_layout)
        self.layout.addWidget(self.connect_button_group_box, 2, 0, alignment=Qt.AlignCenter)

         # 3rd row - Line edit

        self.flowrate_group_box = QGroupBox()
        self.flowrate_button_layout = QHBoxLayout()
        self.flowrate_group_box.setMinimumSize(450, 50)
        # Flowrate instruction Label
        self.flowrate_button_label = QLabel("Enter flowrate:")
        self.font = self.flowrate_button_label.font()
        self.font.setBold(True)
        self.flowrate_button_label.setFont(self.font)
        self.flowrate_button_layout.addWidget(self.flowrate_button_label)
        # Flowrate line edit
        self.flowrate_edit = QLineEdit()
        self.flowrate_edit.setPlaceholderText('Enter an int (0 to 40)')
        self.flowrate_edit.returnPressed.connect(lambda: self.update_flowrate(self.flowrate_edit.text()))
        self.flowrate_button_layout.addWidget(self.flowrate_edit)
        # Current flowrate label
        self.current_flowrate_label = QLabel(f"Current flowrate: {self.current_flowrate} µL/min")
        self.font = self.current_flowrate_label.font()
        self.font.setBold(True)
        self.current_flowrate_label.setFont(self.font)
        self.flowrate_button_layout.addWidget(self.current_flowrate_label)
        # Add to main layout
        self.flowrate_group_box.setLayout(self.flowrate_button_layout)
        self.layout.addWidget(self.flowrate_group_box, 3, 0, alignment=Qt.AlignCenter)

        # Fourth row -  Buttons

        self.buttons_group_box = QGroupBox()
        self.buttons_layout = QHBoxLayout()
        self.buttons_group_box.setMinimumSize(450, 50)
        #Off/on Button
        self.on_off_button = QPushButton('Pump: OFF')
        self.on_off_button.setCheckable(True)
        self.on_off_button.clicked.connect(lambda: self.on_off_button_clicked())
        self.on_off_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.buttons_layout.addWidget(self.on_off_button )
        # Direction Button
        self.direction_button = QPushButton('Direction: OFF')
        self.direction_button.clicked.connect(lambda: self.direction_button_clicked())
        self.direction_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.buttons_layout.addWidget(self.direction_button )
        # Flow behavior dropdown
        self.flow_behavior_dropdown = QComboBox()
        self.flow_behavior_dropdown.addItems(["Continuous","Oscillating", "Pulse"]) # Replace with real flow types
        self.flow_behavior_dropdown.currentTextChanged.connect(self.change_flow_behavior)
        self.buttons_layout.addWidget(self.flow_behavior_dropdown)
        # Add to main layout
        self.buttons_group_box.setLayout(self.buttons_layout)
        self.layout.addWidget(self.buttons_group_box, 4, 0, alignment=Qt.AlignCenter)

        # Fifth row - .txt buttons

        self.text_file_buttons_group_box = QGroupBox()
        self.text_file_buttons_layout = QHBoxLayout()
        self.text_file_buttons_group_box.setMinimumSize(450, 50)
        # Upload .txt file
        self.upload_text_file_button = QPushButton('Upload .txt file')
        self.upload_text_file_button.clicked.connect(lambda: self.upload_text_file_button_clicked())
        self.upload_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.upload_text_file_button )
        # Change .txt file button
        self.change_text_file_button = QPushButton('Change current file')
        self.change_text_file_button.clicked.connect(lambda: self.change_text_file_button_clicked())
        self.change_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.change_text_file_button )
        # Run .txt file button
        self.run_text_file_button = QPushButton('Run .txt file')
        self.run_text_file_button.clicked.connect(lambda: self.run_text_file_button_clicked())
        self.run_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.run_text_file_button )
        # Exit current .txt file button
        self.exit_text_file_button = QPushButton('Exit current file')
        self.exit_text_file_button.clicked.connect(lambda: self.exit_text_file_button_clicked())
        self.exit_text_file_button.setStyleSheet('background-color: #ADD8E6; color: white; padding: 5px;')
        self.text_file_buttons_layout.addWidget(self.exit_text_file_button )
        # Add to main layout
        self.text_file_buttons_group_box.setLayout(self.text_file_buttons_layout)
        self.layout.addWidget(self.text_file_buttons_group_box, 5, 0, alignment=Qt.AlignCenter)

        # Sixth row .txt file names

        self.text_file_names_group_box = QGroupBox()
        self.text_file_names_layout = QVBoxLayout()
        #self.text_file_names_group_box.setMinimumSize(450, 50)
        # Current .txt file label
        self.current_text_file_label = QLabel(f"Current .txt file: {self.fname}")
        self.text_file_names_layout.addWidget(self.current_text_file_label)
        # Add to main layout
        self.text_file_names_group_box.setLayout(self.text_file_names_layout)
        self.layout.addWidget(self.text_file_names_group_box, 6, 0, alignment=Qt.AlignCenter)

    #####################################################################################################################
    # Class Functions
    #####################################################################################################################

    #Connect mulitple pumps
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
    
    # Open Pump that is on a separate arduino
    def new_pump_dropdown_change(self,selected_text):
        try:
            self.current_board = self.connected_boards[self.pump_serial_dict[selected_text]]
            print(f'Connected to {selected_text} with serial {self.pump_serial_dict[selected_text]}')
            self.successful_connection()
            self.current_index = self.new_pump_dropdown.currentIndex()
        except:
            self.new_pump_dropdown.blockSignals(True)
            self.new_pump_dropdown.setCurrentIndex(self.current_index)
            self.new_pump_dropdown.blockSignals(False)
            QMessageBox.warning(self, 'No Connection to this pump', 'No device connected to this pump.\nPlease connect a device and try again.')
        
    # Connect to Arduino port
    def connect_button_clicked(self):
        if self.connected:
            QMessageBox.warning(self, 'Already Connected', 'Device already connected.')
            self.connect_button.setChecked(True)
            return
        try:
            self.current_board , self.new_board_dict= autoport.connect()
            self.connected_boards = self.connected_boards | self.new_board_dict
            #self.pump_serial_dict['Pump 0'] = self.pump_connect
            #print(f'Here is the dict: {self.pump_serial_dict}')
            self.successful_connection()
        except Exception as e:
            self.connect_button.setText("Status: Not Connected")
            self.connect_button.setStyleSheet('color: red;')  # Set color to red for failed connection

    def connect_serial(self,selected_text):
        if self.connected:
            QMessageBox.warning(self, 'Already Connected', 'Device already connected.')
            self.serial_edit.clear()
            return
        try:
            print(selected_text)
            self.current_board = autoport.connect(SERIAL=selected_text)
            self.successful_connection()
        except Exception as e:
            self.connect_button.setText("Status: Not Connected")
            self.connect_button.setStyleSheet('color: red;')
            self.serial_edit.clear()

    # Warn about no connection
    def warn_no_connection(self):
        QMessageBox.warning(self, 'No Connection', 'No device connected. Please connect a device and try again.')
    
    def successful_connection(self):
        self.connect_button.setText("Status: Connected")
        self.connected = True
        self.connect_button.setChecked(True)
        self.connect_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')  # Set color to green for successful connection
        self.is_on = False
        self.on_off_button.setChecked(True)
        self.on_off_button_clicked()
        self.current_flowrate = 1.5
        self.current_flowrate_label.setText(f'Current flowrate: {self.current_flowrate} µL/min')
        self.serial_edit.clear()

    # Turn pump on/off based on button toggle
    def on_off_button_clicked(self):
        if not self.connected or self.current_board ==  None:
            self.warn_no_connection()
            self.on_off_button.setChecked(False)
        elif not self.is_on:
            self.is_on = True
            self.current_board.sendcommand('123')
            #self.arduino_cmds.sendcommand('123')
            self.on_off_button.setText('Pump: ON')
            self.on_off_button.setStyleSheet('background-color: #2eb774; color: white; padding: 5px;')
            if not self.fwd:
                self.direction_button.setText('Direction: <--')
            elif self.fwd:
                self.direction_button.setText('Direction: -->')
        elif self.is_on:
            self.is_on = False
            self.current_board.sendcommand('0')
            #self.arduino_cmds.sendcommand('0')
            self.on_off_button.setText('Pump: OFF')
            self.on_off_button.setStyleSheet('background-color: #bb3f3f; color: white; padding: 5px;')
            self.direction_button.setText('Direction: OFF')
            self.flow_behavior_dropdown.setCurrentIndex(0)


    def direction_button_clicked(self):
        if not self.connected or self.current_board ==  None:
            self.warn_no_connection()
            self.direction_button.setText('Direction: OFF')
        elif not self.is_on:
            self.direction_button.setText('Direction: OFF')
        elif not self.fwd:
            self.fwd = True
            self.current_board.sendcommand('321')
            #self.arduino_cmds.sendcommand('321')
            self.direction_button.setText('Direction: -->')
        elif self.fwd:
            self.fwd = False
            self.current_board.sendcommand('321')
            #self.arduino_cmds.sendcommand('321')
            self.direction_button.setText('Direction: <--')
    

    def update_flowrate(self,new_flowrate):
        if not self.connected or self.current_board ==  None:
            self.warn_no_connection()
            self.flowrate_edit.clear()
            return
        elif not self.is_on:
            self.flowrate_edit.clear()
            return
        
        try:
            self.current_flowrate = int(new_flowrate)
            if self.current_flowrate >=0 and self.current_flowrate <= 40:
                self.current_board.sendcommand(str(self.current_flowrate))
                #self.arduino_cmds.sendcommand(str(self.current_flowrate))
                self.current_flowrate_label.setText(f"Current flowrate: {self.current_flowrate} µL/min")
                print(f"Flowrate updated to: {self.current_flowrate}")
            else:
                raise ValueError("Must be between 0 and 40")
        except ValueError:
            print("Invalid flowrate entered. Please enter a number.")
        finally:
            self.flowrate_edit.clear()
    
    # Change flow behvior -- needs to be added to arduino
    def change_flow_behavior(self,selected_text):
        if not self.connected or self.current_board ==  None:
            self.warn_no_connection()
            self.flow_behavior_dropdown.setCurrentIndex(0)
            return
        elif not self.is_on:
            self.flow_behavior_dropdown.setCurrentIndex(0)
            return

        if selected_text == "Continuous":
            self.current_board.sendcommand('FLOWA')
            #self.arduino_cmds.sendcommand('FLOWA')
        elif selected_text == "Oscillating":
            self.current_board.sendcommand('FLOWB')
            #self.arduino_cmds.sendcommand('FLOWB')
        elif selected_text == "Pulse":
            self.current_board.sendcommand('FLOWC')
            #self.arduino_cmds.sendcommand('FLOWC')

    def upload_text_file_button_clicked(self):
        self.fname, _ = QFileDialog.getOpenFileName(self, "Open File", "", ".txt Files (*.txt)")
        if self.fname:
            self.selected_file = self.fname # Save as the selected file
            self.current_text_file_label.setText(f"Current File Selected: {self.fname}")
            self.current_file_tracker = 0
            self.text_file_count += 1
            self.text_file_list.append(self.fname)
            new_label = QLabel(f"{self.text_file_count}. {self.fname[-15:]}")
            self.text_file_names_layout.addWidget(new_label)

    def change_text_file_button_clicked(self):
        if self.text_file_count >= 1:
            self.current_text_file_label.setText(f"Current File Selected: {self.text_file_list[self.current_file_tracker]}")
            self.fname = self.text_file_list[self.current_file_tracker]
            self.current_file_tracker +=1
            if self.current_file_tracker == len(self.text_file_list):
                self.current_file_tracker = 0

    """ def run_text_file_button_clicked(self):
        if not hasattr(self, 'fname') or not self.fname:
            QMessageBox.warning(self, "No File", "Please select a text file first.")
            return 

        now = time.monotonic()
        new_commands = []
        try:
            with open(self.fname, 'r') as file:
                raw_commands = " ".join(file.readlines()).split("%%%%%%%%%")

                for cmd in raw_commands:
                    if "#########" in cmd:
                        try:
                            command_str, timestamp_str = cmd.strip().split("#########")

                            command = command_str.strip()  # keep as string
                            timestamp = float(timestamp_str.strip())
                            execute_time = now + timestamp

                            new_commands.append((execute_time, command))

                        except ValueError:
                            print(f"Skipping malformed command: {cmd.strip()}")
                            continue

            #Sort commands by timestamp
            new_commands.sort(key=lambda x: x[0])

            if self.worker_running:
                self.scheduled_commands += new_commands
                self.scheduled_commands.sort(key=lambda x: x[0])
                print("Scheduled commands:", self.scheduled_commands)
            elif not self.worker_running:
                self.scheduled_commands = new_commands
                print("Scheduled commands:", self.scheduled_commands)

                # Launch QThread worker
                self.thread = QThread()
                self.worker = self.CommandRunner(self.scheduled_commands,self)
                self.worker.moveToThread(self.thread)

                self.worker.log.connect(self.handle_log) 
                # Connect signals
                self.thread.started.connect(self.worker.run)
                self.worker.finished.connect(self.thread.quit)
                self.worker.finished.connect(self.worker.deleteLater)
                self.thread.finished.connect(self.thread.deleteLater)
                self.thread.finished.connect(self.worker.close_worker)
                self.thread.start()
                self.worker_running = True

        except Exception as e:
            QMessageBox.critical(self, "File Error", f"An error occurred while reading the file:\n{str(e)}") """
    
    def run_text_file_button_clicked(self):
        if not hasattr(self, 'fname') or not self.fname:
            QMessageBox.warning(self, "No File", "Please select a text file first.")
            return 
        if self.connected_boards == {}:
            QMessageBox.warning(self, "No Boards Connected", "Please connect a board first.")
            return

        now = time.monotonic()
        new_commands = []

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

                            # Validate board exists
                            if serial in self.connected_boards:
                                board = self.connected_boards[serial]
                                new_commands.append((execute_time, command, board))
                            else:
                                # Fallback: if exactly one board is connected, run on it.
                                unique_boards = list({id(b): b for b in self.connected_boards.values()}.values())
                                if len(unique_boards) == 1:
                                    board = unique_boards[0]
                                    print(
                                        f"Unknown serial: {serial}. "
                                        f"Falling back to the only connected board."
                                    )
                                    new_commands.append((execute_time, command, board))
                                else:
                                    print(
                                        f"Unknown serial: {serial}, skipping command. "
                                        f"Known keys: {list(self.connected_boards.keys())}"
                                    )
                                    continue

                        except ValueError as e:
                            print(f"Malformed entry: {entry} -- {e}")
                            continue

            # Sort by execution time
            new_commands.sort(key=lambda x: x[0])

            # Handle existing or new thread
            if self.worker_running:
                self.scheduled_commands += new_commands
                self.scheduled_commands.sort(key=lambda x: x[0])
                print('command worker is already running')
            elif not self.worker_running:
                self.scheduled_commands = new_commands

                # Start worker
                self.thread = QThread()
                self.worker = self.CommandRunner(self.scheduled_commands, self)
                self.worker.moveToThread(self.thread)

                self.worker.log.connect(self.handle_log)
                self.thread.started.connect(self.worker.run)
                self.worker.finished.connect(self.thread.quit)
                self.worker.finished.connect(self.worker.deleteLater)
                self.thread.finished.connect(self.thread.deleteLater)
                #self.thread.finished.connect(self.worker.close_worker)
                self.worker.finished.connect(self.worker.close_worker)
                self.thread.start()
                self.worker_running = True

        except Exception as e:
            print('file error')
            QMessageBox.critical(self, "File Error", f"Error reading the file:\n{str(e)}")

        
    def handle_log(self, emission):

        info = emission.split('*********')
        #print(info)
        board = info[0]
        #self.current_board = board
        command = info[1]
        #print(f'Handling command from log: {command}')
        # UI updates safe here
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
            self.flow_behavior_dropdown.setCurrentIndex(0)
        elif command == '321':
            self.fwd = not self.fwd
            self.direction_button.setText('Direction: -->' if self.fwd else 'Direction: <--')
        elif 'FLOW' in command:
            if command == 'FLOWA':
                self.flow_behavior_dropdown.setCurrentIndex(0)
            elif command == 'FLOWB':
                self.flow_behavior_dropdown.setCurrentIndex(1)
            elif command == 'FLOWC':
                self.flow_behavior_dropdown.setCurrentIndex(2)
        else:
            try:
                self.current_flowrate = int(command)
                if 0 <= self.current_flowrate <= 40:
                    self.current_flowrate_label.setText(f"Current flowrate: {self.current_flowrate} µL/min")
                    print(f"Flowrate updated to: {self.current_flowrate}")
                else:
                    raise ValueError("Must be between 0 and 40")
            except ValueError:
                print("Invalid flowrate entered. Please enter a number.")
        
    def exit_text_file_button_clicked(self):
        if not self.connected or self.current_board ==  None:
            self.warn_no_connection()
        elif self.worker and self.thread and self.thread.isRunning():
            self.worker.stop()
            self.thread.quit()
            #self.thread.wait()

            self.scheduled_commands = []
            self.worker_running = False
            self.is_on = True
            self.on_off_button_clicked()
            self.on_off_button.setChecked(False)
            print('Thread Exited.')


    #####################################################################################################################
            # QWorker sub-class
    #####################################################################################################################


    class CommandRunner(QObject):
        finished = pyqtSignal()
        log = pyqtSignal(str)

        def __init__(self, scheduled_commands,main_window):
            super().__init__()
            self.scheduled_commands = scheduled_commands
            self._is_running = True
            self.arduino_cmds = arduino_cmds.PumpFluidics()
            self.main_window = main_window

        def run(self):
            try:
                for execute_time, command, board in self.scheduled_commands:
                    while self._is_running:
                        wait_time = execute_time - time.monotonic()
                        if wait_time <= 0:
                            break
                        time.sleep(min(wait_time, 0.1))

                    if not self._is_running:
                        break

                    self.log.emit(f"{board}*********{command}")
                    self.main_window.current_board = board
                    self.execute_command(command, board)

            finally:
                self.finished.emit()

        def execute_command(self, command, board):
            if command.startswith('FLOW'):
                return
            else:
                board.sendcommand(str(command))

        """ def run(self):
            for execute_time, command in self.scheduled_commands:
                while self._is_running:
                    wait_time = execute_time - time.monotonic()
                    if wait_time <= 0:
                        break
                    time.sleep(min(wait_time, 0.1))  # Sleep in small chunks to allow interruption - may be better way to do this

                if not self._is_running:
                    break

                self.log.emit(f"Running command: {command}")
                self.execute_command(command)

            self.finished.emit() """

        def stop(self):
            self._is_running = False

        def stop_worker(self):
            if hasattr(self, 'worker'):
                self.worker.stop()
        
        def close_worker(self):
            print('close worker called')
            self.main_window.worker_running = False

        """ def execute_command(self, command):
            if command.startswith('FLOW'):
                return
            else:
                self.arduino_cmds.sendcommand(str(command)) """

    #####################################################################################################################
            # Multi pump window sub-class
    #####################################################################################################################

    class SetMultiSerials(QWidget):
        data_emitted = pyqtSignal(dict)
        def __init__(self,num_pumps):
            super().__init__()
            self.setWindowTitle("Set pump serials")
            self.setGeometry(200, 200, 300, 200)

            # Layout
            self.layout = QGridLayout()
            self.setLayout(self.layout)

            self.line_edits = []
            self.serial_dict = {}

            if num_pumps > 10:
                num_pumps = 10

            for i in range(num_pumps):
                line_edit = QLineEdit()
                line_edit.setPlaceholderText(f'Enter Pump {i+1} serial #')
                self.layout.addWidget(line_edit)
                self.line_edits.append(line_edit)
            
            self.button = QPushButton("Collect Serial #s")
            self.button.clicked.connect(self.collect_serials)
            self.layout.addWidget(self.button)

        def collect_serials(self):
            for i, line_edit in enumerate(self.line_edits):
                #print(f"Pump {i+1}: {line_edit.text()}")
                self.serial_dict[f'Pump {i+1}'] = line_edit.text()
            #print(self.serial_dict)

            self.data_emitted.emit(self.serial_dict)
            self.close()

            

