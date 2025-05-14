// --------------------------
// Pin Definitions
// --------------------------
const int contactPin = 2;      // Contact detection pin with pullup
const int contactLowPin = 3;   // Pin that goes LOW when contact detected
const int PUL_PIN = 9;         // Pulse pin
const int DIR_PIN = 10;        // Direction pin
const int ENA_PIN = 11;        // Enable pin

// --------------------------
// Variables
// --------------------------
const int stepDelay = 100;     // Microseconds between steps
const double MM_PER_PULSE = 0.00005080;  // 20 TPI = 0.05in/rev = 1.27mm/rev, 25000 pulse/rev = 0.0000508mm/pulse
double currentPosition= -999; // -999 to indicate null value
unsigned long lastPositionUpdate = 0;
const int STEPS_PER_COMMAND = 20;

// --------------------------
// Flags
// --------------------------
volatile bool contactDetected = false;
volatile bool forceRest = false;
bool isCalibrated = false;
bool manualControlActive = false;


// --------------------------
// Setup
// --------------------------
void setup() {
  pinMode(contactPin, INPUT_PULLUP);
  pinMode(contactLowPin, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(contactPin), contactInterruptHandler, FALLING);
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);

  Serial.begin(9600);
  Serial.println("Arduino ready.");
}

// --------------------------
// Listener
// --------------------------
void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "CALIBRATE") {
      runCalibration();
    }
    else if (command.startsWith("TARGET:")) {
      float targetDist = command.substring(7).toFloat();
      moveToTarget(targetDist);
    }
    else if (command == "MANUAL:READY") {
      manualControlActive = true;
    }
    else if (command == "MANUAL:COMPLETE") {
      manualControlActive = false;
      Serial.println("STATUS:MANUAL_COMPLETE");
    }
    else if (command == "MANUAL:CW" && manualControlActive) {
      manualStepCW();
    }
    else if (command == "MANUAL:CCW" && manualControlActive) {
      manualStepCCW();
    }
    else if (command == "MANUAL:STOP") {
      manualStopMotor();
    }
    else if (command == "REST") {
      stopMotor();
    }
    else {
      Serial.println("Unknown command: " + command);
    }
  }
}

// --------------------------
// Calibration Routine
// --------------------------
void runCalibration() {
  Serial.println("STATUS:CALIBRATION_START");
  digitalWrite(contactLowPin, LOW);
  digitalWrite(DIR_PIN, LOW); // CCW
  digitalWrite(ENA_PIN, LOW);
  contactDetected = false;
  if (digitalRead(contactPin) == LOW) {
    contactDetected = true;
    Serial.println("Contact already detected!");
  } else {
    // Only run motor if not already in contact
    while (!contactDetected) {
      stepMotor();
    }
  }
  currentPosition = 0;
  isCalibrated = true;
  digitalWrite(ENA_PIN, HIGH);
  Serial.println("POSITION:0");
  Serial.println("STATUS:CALIBRATION_COMPLETE");
}

// --------------------------
// Target Distance Routine
// --------------------------
void moveToTarget(float mm) {
  if (!isCalibrated) {
    Serial.println("ERROR:NOT_CALIBRATED");
    return;
  }
  
  Serial.print("Moving to target distance: ");
  Serial.println(mm, 6);
  
  // Calculate how many steps we need to move
  long targetSteps = round(mm / MM_PER_PULSE);
  float snappedTarget = targetSteps * MM_PER_PULSE;
  long stepsToMove = round((snappedTarget - currentPosition) / MM_PER_PULSE);

  Serial.print("Steps to move: ");
  Serial.println(stepsToMove);  // Debug output
  
  // Set direction based on whether we need to move forward or backward
  if (stepsToMove > 0) {
    digitalWrite(DIR_PIN, HIGH);  // Move away from contact point
  } else {
    digitalWrite(DIR_PIN, LOW); // Move toward contact point
  }
  
  // Enable motor
  digitalWrite(ENA_PIN, LOW);
  delay(10); // Short delay to ensure enable takes effect
  
  // Take absolute value for the loop
  long absStepsToMove = abs(stepsToMove);

  // Store starting position for progress reports
  double startPosition = currentPosition;

  // Move the motor one step at a time
  for (long i = 0; i < absStepsToMove; i++) {
    stepMotor();
    
    if (stepsToMove > 0) {
      currentPosition = startPosition + (i * MM_PER_PULSE);
    } else {
      currentPosition = startPosition - (i * MM_PER_PULSE);
    }

    if (i % 100 == 0) {  // Update every 1000 steps (about 0.05mm)
      Serial.print("POSITION:");
      Serial.println(currentPosition, 6);
    }

    // Safety check - stop if contact detected while moving toward home
    if (digitalRead(contactPin) == LOW && digitalRead(DIR_PIN) == LOW) {
      Serial.print("POSITION:");
      Serial.println(currentPosition, 6);
      Serial.println("ERROR:Unexpected contact detected!");
      break;
    }
  }
  
  Serial.print("POSITION:");
  Serial.println(currentPosition, 6);
  Serial.println("STATUS:TARGET_COMPLETE");
}

// --------------------------
// Manual Control Routine
// --------------------------
void manualStepCCW() {
  if (!isCalibrated) {
    Serial.println("ERROR:NOT_CALIBRATED");
    return;
  }
  
  digitalWrite(DIR_PIN, LOW);
  digitalWrite(ENA_PIN, LOW);
  
  // Check if already in contact before trying to move
  contactDetected = false;
  if (digitalRead(contactPin) == LOW) {
    contactDetected = true;
    Serial.println("WARNING: Contact already detected!");
    return;
  }
  
  // Take multiple steps per command
  for (int i = 0; i < STEPS_PER_COMMAND; i++) {
    // Check for contact during steps
    if (digitalRead(contactPin) == LOW) {
      contactDetected = true;
      Serial.println("WARNING: Contact detected during movement!");
      break;
    }
    // Only move if not in contact
    stepMotor();
    currentPosition -= MM_PER_PULSE;
  }
}

void manualStepCW() {
  if (!isCalibrated) {
    Serial.println("ERROR:NOT_CALIBRATED");
    return;
  }
  
  digitalWrite(DIR_PIN, HIGH);
  digitalWrite(ENA_PIN, LOW);
  
  // Take multiple steps per command
  for (int i = 0; i < STEPS_PER_COMMAND; i++) {
    stepMotor();
    currentPosition += MM_PER_PULSE;
  }
}

void manualStopMotor() {
  Serial.print("POSITION:");
  Serial.println(currentPosition, 6);
}

// --------------------------
// REST Routine
// --------------------------
void stopMotor() {
  Serial.println("Entering Rest State.");
  digitalWrite(ENA_PIN, HIGH);
  Serial.print("POSITION:");
  Serial.println(currentPosition, 6);
}

// --------------------------
// Step Pulse Generator
// --------------------------
void stepMotor() {
  digitalWrite(PUL_PIN, HIGH);
  delayMicroseconds(stepDelay);
  digitalWrite(PUL_PIN, LOW);
  delayMicroseconds(stepDelay);
}

// --------------------------
// Contact Interrupt
// --------------------------
void contactInterruptHandler() {
  contactDetected = true;
}

// --------------------------
// Rest Interrupt
// --------------------------
void forceRestInterruptHandler(){
  forceRest = true;
}
