

# Use microfluidics.py as a reference
import time
import serial

class PumpFluidics:
    
    comPort = ""

    properties = {"comPort": ""}

    # private constant vars
    __SERIAL_BAUDRATE__ = 9600
    __SERIAL_TIMEOUT__ = 3

    def connect(self):
        serialObject = serial.Serial(
            self.comPort, 
            baudrate=self.__SERIAL_BAUDRATE__, 
            timeout=self.__SERIAL_TIMEOUT__)
        
        self.properties["serial"] = serialObject

        while(self.properties["serial"].readline().strip() !=  b'READY'):
            continue
    
    def sendcommand(self, command):
        self.properties["serial"].write(command.encode())
        print(f'Command sent: {command}')
        time.sleep(0.01)