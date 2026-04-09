/*
  RGB LED Strip Control via L298N Motor Driver
  
  WIRING INSTRUCTIONS:
  1. Power: Connect your 12V Power Supply to the L298N "12V" terminal. 
     Connect the L298N "GND" to the Power Supply GND AND the Arduino GND.
  2. RGB Strip (Assuming standard Common Anode 12V strip):
     - Strip 12V (or +) -> Connect directly to 12V power supply.
     - Strip Red (R)    -> L298N OUT1
     - Strip Green (G)  -> L298N OUT2
     - Strip Blue (B)   -> L298N OUT3
  3. L298N Control Pins:
     - ENA & ENB jumpers -> LEAVE THEM ON (keeps channels enabled).
     - IN1 -> Arduino Pin 9 (PWM)
     - IN2 -> Arduino Pin 10 (PWM)
     - IN3 -> Arduino Pin 11 (PWM)
  4. Button:
     - Connect one leg of the button to Arduino Pin 2.
     - Connect the other leg of the button to Arduino GND.
*/

// --- Configuration ---
const int buttonPin = 2; // Button pin
const int pinR = 9;      // L298N IN1
const int pinG = 10;     // L298N IN2
const int pinB = 11;     // L298N IN3

// Change to false if your RGB strip shares a Common Cathode (Ground) instead of 12V
const bool isCommonAnode = true; 

// Base color for the IDLE "glow" (0-255) - Currently set to White
const int idleColorR = 255;
const int idleColorG = 255;
const int idleColorB = 255;

// Base color for the ACTIVE state (Flicker and 10s hold) - Currently set to White
const int activeColorR = 255;
const int activeColorG = 255;
const int activeColorB = 255;

// --- State Variables ---
unsigned long previousMillis = 0;
int lastButtonState = HIGH;
int brightness = 0;
int fadeAmount = 3;       // How fast it breathes (higher = faster)
const int glowSpeed = 20; // Delay between brightness steps in ms

void setup() {
  // Setup pins
  Serial.begin(9600);
  pinMode(buttonPin, INPUT_PULLUP); // Uses internal pull-up resistor
  pinMode(pinR, OUTPUT);
  pinMode(pinG, OUTPUT);
  pinMode(pinB, OUTPUT);

  // Initialize LEDs to off
  setColor(0, 0, 0);
}

void loop() {
  // Check if button is pressed (LOW because of INPUT_PULLUP)
  int sensorVal = digitalRead(buttonPin);

  // Only print if state has changed (prevents Serial flooding)
  if (sensorVal != lastButtonState) {
    Serial.println(sensorVal);
    lastButtonState = sensorVal;
  }

  if (sensorVal == LOW) {
    // --- 1. Flicker fast 5 times ---
    for (int i = 0; i < 5; i++) {
      setColor(activeColorR, activeColorG, activeColorB); // ON
      delay(60); 
      setColor(0, 0, 0);                                  // OFF
      delay(60);
    }

    // --- 2. Stay on for 10 seconds ---
    setColor(activeColorR, activeColorG, activeColorB);
    delay(10000); 

    // --- 3. Clean up and prevent immediate re-triggering ---
    setColor(0, 0, 0); // Turn off briefly before resuming glow
    
    // Wait until the user actually releases the button
    while(digitalRead(buttonPin) == LOW) {
      delay(10);
    }
    
    // Reset glow variables so it starts breathing from 0 smoothly
    brightness = 0;
    fadeAmount = abs(fadeAmount); 
    delay(100); 
  } 
  else {
    // --- IDLE STATE: Breathing Glow Effect ---
    // Using millis() instead of delay() so the Arduino can still instantly read the button
    unsigned long currentMillis = millis();
    
    if (currentMillis - previousMillis >= glowSpeed) {
      previousMillis = currentMillis;

      // Calculate the scaled RGB values based on current brightness
      int r = (idleColorR * brightness) / 255;
      int g = (idleColorG * brightness) / 255;
      int b = (idleColorB * brightness) / 255;
      
      setColor(r, g, b);

      // Increment/Decrement brightness for the next loop
      brightness = brightness + fadeAmount;

      // Reverse the direction of the fading at the ends
      if (brightness <= 0 || brightness >= 255) {
        fadeAmount = -fadeAmount;
        // Keep it bounded
        brightness = constrain(brightness, 0, 255); 
      }
    }
  }
}

// Helper function to set the color, handling standard L298N logic 
void setColor(int r, int g, int b) {
  if (isCommonAnode) {
    // For common anode, 255 on an IN pin = 12V on OUT pin = LED OFF (0 potential difference)
    // 0 on an IN pin = GND on OUT pin = LED ON (12V potential difference)
    analogWrite(pinR, 255 - r);
    analogWrite(pinG, 255 - g);
    analogWrite(pinB, 255 - b);
  } else {
    // Standard direct logic
    analogWrite(pinR, r);
    analogWrite(pinG, g);
    analogWrite(pinB, b);
  }
}