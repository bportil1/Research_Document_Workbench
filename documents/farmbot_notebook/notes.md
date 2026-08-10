# FarmBot Local Development and Automated Imaging

## Development Notebook

*Developer:** Bryan Portillo
**Institution:** Montana State University
**Project:** FarmBot Local Development and Precision Agriculture Extension
**Current FarmBot OS Base:** v15.5.2 (`staging`, commit `65b5c05d`)
**Current FarmBot Web App Base:** v15.30.1 (`staging`, commit `5796fb3ac`)
**Hardware:** FarmBot Genesis v1.7, Raspberry Pi 4, Farmduino
**Current Status:** Local development platform operational; automated imaging experiment under active development

---

## 1. Project Objective

The objective of this work is to create a development environment in which FarmBot functionality can be modified at both the robot operating-system level and the user-interface level.

The immediate application is an automated plant imaging workflow. The intended behavior is for FarmBot to obtain plant information, move the camera to plant locations, and collect photographs without requiring the user to manually move the machine to each plant.

A secondary but important objective is to expose this functionality through the FarmBot web interface. Implementing the functionality exclusively inside FarmBot OS would require a developer to invoke custom backend functionality directly and would therefore not provide a practical workflow for normal FarmBot users.

The project consequently required development access to both:

* FarmBot OS running on the Raspberry Pi.
* The FarmBot Web App used to configure and control the device.
* The API and message-broker infrastructure connecting the two.
* The physical FarmBot hardware.

---

## 2. Development Strategy

Development was divided into three general stages.

### 2.1 Local FarmBot OS Development

A local FarmBot OS development environment was established to allow the existing Nerves/Elixir application to be compiled, modified, and tested independently of the production FarmBot infrastructure.

Early development focused on understanding:

* The FarmBot OS supervision tree.
* Host versus Raspberry Pi build targets.
* Configuration and startup behavior.
* Farmduino/UART detection.
* Hardware abstraction.
* FarmBot's network configurator.
* MQTT/RPC communication.
* The relationship between FarmBot OS and the FarmBot Web App.

A prototype supervised process was then introduced as the basis for autonomous routines.

### 2.2 Local FarmBot Web App

A local instance of the FarmBot Web App was established so that changes to FarmBot OS could be paired with corresponding user-interface functionality.

This environment provides locally controlled versions of the:

* FarmBot frontend.
* Rails API.
* PostgreSQL database.
* Message broker.
* FarmBot account and device state.

The local deployment is currently configured around the development laptop at:

```text
10.42.0.1
```

The local API is exposed at:

```text
http://10.42.0.1:3000
```

MQTT WebSocket communication is configured through:

```text
ws://10.42.0.1:3002/ws
```

### 2.3 Physical FarmBot Integration

A custom FarmBot OS firmware image was built for the Raspberry Pi 4 and flashed to the FarmBot microSD card.

The FarmBot was then configured to use the local development server rather than the hosted FarmBot service.

This provided the complete development path:

```text
Modified FarmBot Web Interface
            |
            v
    Local FarmBot Web App
            |
     +------+------+
     |             |
     v             v
 Rails API      Database
     |
     v
Message Broker
     |
     v
 FarmBot OS
 Raspberry Pi 4
     |
 +---+----------------+
 |                    |
 v                    v
Custom             Farmduino
Experiments            |
 |                     v
 +--------------> Physical FarmBot
                  Motors / Camera
```

---

## 3. Local Network Configuration

The development laptop provides the FarmBot's wired network connection.

The Ethernet development network uses:

```text
Development Laptop: 10.42.0.1
FarmBot: DHCP-assigned address
```

During successful physical testing, the FarmBot received:

```text
10.42.0.49
```

The FarmBot was therefore able to reach services hosted on the development laptop while the laptop provided access to the necessary network resources.

The FarmBot's onboard network configurator was accessible on TCP port `4000` during configuration.

For example:

```text
http://10.42.0.49:4000/network
```

The available physical interfaces included:

```text
eth0
wlan0
```

For the current development configuration, `eth0` was selected.

IPv4 configuration used:

```text
IP Method: DHCP
```

The FarmBot account configuration was then pointed at the local FarmBot server:

```text
http://10.42.0.1:3000
```

This server setting is essential to the local development configuration.

Without redirecting FarmBot OS to the local server, the robot would continue attempting to use the standard hosted FarmBot infrastructure rather than the locally modified application.

---

## 4. Local FarmBot Web Application

### 4.1 Base Version

The local FarmBot Web App currently uses:

```text
Branch: staging
Base commit: 5796fb3ac
Tag: v15.30.1
```

The current working tree contains modifications to both backend and frontend components.

---

### 4.2 Backend Modifications

Current modified backend files include:

```text
app/controllers/api/tokens_controller.rb
app/lib/rmq_config_writer.rb
app/lib/session_token.rb
config/application.rb
```

These modifications were introduced while configuring the local API and MQTT infrastructure for communication with the physical FarmBot.

The current environment contains:

```text
API_HOST=10.42.0.1
API_PORT=3000
MQTT_HOST=10.42.0.1
MQTT_WS=ws://10.42.0.1:3002/ws
MQTT_VHOST=/
```

During development, token inspection verified that a locally issued FarmBot session token contained the expected local connection information:

```text
mqtt: 10.42.0.1
mqtt_ws: ws://10.42.0.1:3002/ws
vhost: /
iss: http://10.42.0.1:3000
```

Correct construction of the API issuer was one important part of the local-server integration.

An intermediate configuration generated:

```text
//10.42.0.1:3000
```

rather than:

```text
http://10.42.0.1:3000
```

The configuration was subsequently corrected so that locally generated tokens identify the complete HTTP API address.

This debugging demonstrated that API, MQTT, WebSocket, and token configuration must be treated as a coordinated system when FarmBot is operated against a nonstandard server.

---

### 4.3 Frontend Modifications

Current frontend modifications include:

```text
frontend/__test_support__/fake_camera_data.ts
frontend/devices/actions.ts
frontend/photos/interfaces.ts
frontend/photos/photos.tsx
frontend/photos/reducer.ts
frontend/photos/automated_imaging/
```

The new directory:

```text
frontend/photos/automated_imaging/
```

contains the primary frontend work associated with the automated imaging experiment.

The purpose of this interface work is to expose autonomous imaging functionality through the FarmBot Web App rather than requiring users to interact directly with FarmBot OS or invoke backend functionality manually.

This is an important design requirement of the project. The FarmBot OS functionality provides the physical behavior, while the modified web interface provides a practical user-facing method for controlling it.

---

## 5. FarmBot OS

### 5.1 Base Version

The current FarmBot OS development tree uses:

```text
Branch: staging
Base commit: 65b5c05d
Version: v15.5.2
Target: Raspberry Pi 4
```

Firmware metadata from the current development image reports:

```text
Product: farmbot
Description: The Brains of the Farmbot Project
Version: 15.5.2
Platform: rpi4
Architecture: arm
Build branch: staging
VCS identifier: 65b5c05d62578df67de175a27e655e121620c22d
Nickname: club-kiwi
```

---

### 5.2 Modified FarmBot OS Files

The current FarmBot OS working tree contains modifications to:

```text
.tool-versions
config/target.exs
lib/farmbot_os.ex
lib/firmware/uart_detector.ex
lib/os/configurator/config_data_layer.ex
lib/os/configurator/supervisor.ex
lib/os/lua.ex
```

New files and directories include:

```text
lib/experiments/
lib/os/lua/automated_imaging.ex
lib/photo_collection.ex
test/os/lua/ext/automated_imaging_test.exs
```

The currently identified photo-collection-specific files include:

```text
lib/photo_collection.ex
lib/experiments/photo_collection/plant_source.ex
lib/os/lua/automated_imaging.ex
```

These changes span three general areas:

1. Development and hardware configuration.
2. Local-server and configurator support.
3. Automated imaging functionality.

---

## 6. Automated Imaging Architecture

The automated imaging implementation is divided between the modified web interface and FarmBot OS.

At a high level:

```text
Automated Imaging UI
        |
        v
FarmBot Command / RPC
        |
        v
FarmBot OS Lua Integration
        |
        v
FarmbotOS.PhotoCollection
        |
   +----+----+
   |         |
   v         v
Plant      Hardware
Source     Operations
             |
        +----+----+
        |         |
        v         v
      Motion    Camera
```

At the FarmBot OS level, the primary long-running component currently under development is:

```text
FarmbotOS.PhotoCollection
```

The module is implemented as a supervised `GenServer`.

Its purpose is to coordinate the automated imaging operation rather than placing all autonomous behavior directly inside the web application.

Plant acquisition is separated from the collection process through a plant-source abstraction.

The current relevant source file is:

```text
lib/experiments/photo_collection/plant_source.ex
```

This separation is intended to prevent the physical collection process from being tightly coupled to one specific source of plant information.

The automated imaging functionality is also exposed through FarmBot OS's Lua integration using:

```text
lib/os/lua/automated_imaging.ex
```

The exact command path and implementation details should be documented after the current versions of these modules have been inspected.

---

## 7. Building and Flashing FarmBot OS

The custom FarmBot OS firmware is built for the Raspberry Pi 4 target.

The resulting firmware image is located at:

```text
_build/rpi4/rpi4_dev/nerves/images/farmbot.fw
```

The firmware can be inspected using:

```bash
/usr/local/bin/fwup \
  -m \
  -i _build/rpi4/rpi4_dev/nerves/images/farmbot.fw
```

A firmware archive can be validated using:

```bash
sudo /usr/local/bin/fwup \
  -V \
  -i _build/rpi4/rpi4_dev/nerves/images/farmbot.fw \
  -t complete \
  -d /dev/sdX
```

The microSD card can then be flashed using:

```bash
sudo /usr/local/bin/fwup \
  -a \
  -i _build/rpi4/rpi4_dev/nerves/images/farmbot.fw \
  -t complete \
  -d /dev/sdX
```

Where:

```text
/dev/sdX
```

must be replaced with the actual block device corresponding to the microSD card.

**The target device must always be verified before running `fwup`. Selecting the wrong block device can overwrite another disk.**

---

## 8. Important Firmware Development Discovery

One important issue encountered during physical development involved the relationship between the source tree and generated firmware.

Editing FarmBot OS source files does **not** modify an already-generated `.fw` image.

During one debugging session, source modifications made in August were being tested using a firmware image whose modification date was still July 31.

As a result, reflashing the card successfully did not deploy the latest source changes. It repeatedly installed the older firmware image.

Firmware timestamps can be inspected using:

```bash
stat _build/rpi4/rpi4_dev/nerves/images/farmbot.fw
```

Relevant source timestamps can similarly be checked using:

```bash
stat path/to/modified/file.ex
```

Firmware metadata can be checked using:

```bash
/usr/local/bin/fwup \
  -m \
  -i _build/rpi4/rpi4_dev/nerves/images/farmbot.fw
```

The correct development process is therefore:

```text
Modify Source
     |
     v
Compile / Test
     |
     v
Build New Firmware
     |
     v
Verify Firmware Timestamp and Metadata
     |
     v
Flash microSD
     |
     v
Boot FarmBot
     |
     v
Configure Local Server
     |
     v
Verify Connectivity
     |
     v
Perform Physical Test
```

A successful `fwup` operation only establishes that the selected firmware image was written successfully. It does not establish that the image contains the most recent source modifications.

---

## 9. Physical Integration

After flashing the custom firmware, the FarmBot boots into its network configuration environment.

The physical development sequence used during successful testing was approximately:

```text
Flash custom FarmBot OS
        |
        v
Insert microSD into Raspberry Pi
        |
        v
Boot FarmBot
        |
        v
Connect Ethernet to development laptop
        |
        v
FarmBot obtains DHCP address
        |
        v
Open FarmBot configurator
        |
        v
Select eth0
        |
        v
Use DHCP
        |
        v
Enter FarmBot account credentials
        |
        v
Set server to:
http://10.42.0.1:3000
        |
        v
Finish configuration
        |
        v
FarmBot connects to local API/broker
```

The FarmBot's presence on the local Ethernet network can be checked using:

```bash
ip neigh
```

During successful development, the device appeared as:

```text
10.42.0.49 dev eno1 lladdr d8:3a:dd:6b:55:4c
```

The MAC address therefore provided an additional method of identifying the physical FarmBot during network debugging.

---

## 10. Verified End-to-End Operation

The local development environment has reached successful end-to-end physical operation.

A successful FarmBot status report showed:

```text
Device ID: 1

Version: v15.5.2

Model: Genesis v1.7

Firmware:
v6.6.26 Farmduino (Genesis v1.7)

CPU temperature:
42 C

Memory usage:
69 MB

Voltage:
Good

Camera:
Connected

Raspberry Pi:
4

Connectivity code:
31

Diagnosis:
All systems nominal
```

The connectivity status also established communication across:

```text
This Computer -> Internet
This Computer -> Message Broker
FarmBot -> Message Broker
FarmBot -> Web App
Raspberry Pi -> Farmduino
```

This demonstrated successful integration of:

```text
Browser
   |
   v
Modified Web Interface
   |
   v
Local Web Application
   |
   v
Rails API
   |
   v
Message Broker
   |
   v
FarmBot OS
   |
   v
Raspberry Pi 4
   |
   v
Farmduino
   |
   v
Physical FarmBot
```

Physical movement and camera operation were also successfully exercised through the interface.

This represents the primary infrastructure milestone of the project.

---

## 11. Current Automated Imaging Testing

After establishing the complete local environment, development moved to testing the custom automated imaging experiment.

Two current implementation issues have been observed.

### 11.1 No-Plants Result Serialization

An initial experiment execution returned:

```elixir
{:error, :no_plants}
```

The interface subsequently reported:

```text
Protocol.UndefinedError

protocol:
Jason.Encoder

value:
{:error, :no_plants}

description:
Jason.Encoder protocol must always be explicitly implemented
```

This indicates that the experiment result eventually crosses a JSON serialization boundary.

An arbitrary Elixir tuple such as:

```elixir
{:error, :no_plants}
```

cannot be directly encoded by Jason without an appropriate encoder.

This does **not** indicate a failure of the local FarmBot infrastructure.

Instead, the experiment's externally returned value should be converted to a JSON-compatible structure.

For example:

```elixir
%{
  status: "error",
  error: "no_plants"
}
```

Internal Elixir code can continue using tuples where appropriate, while the boundary exposed to the interface should return JSON-safe data.

---

### 11.2 Physical Execution Timeout

After plants were added and physical movement and camera functionality had been verified, another automated imaging execution reached:

```text
{:timeout,
 {GenServer, :call,
  [FarmbotOS.PhotoCollection, :run_now, 5000]}}
```

The current call therefore allows approximately five seconds for the `PhotoCollection` process to return.

A physical operation involving robot movement and image capture can reasonably require more than five seconds.

The current implementation therefore needs to determine whether the operation should:

1. Use a longer bounded timeout.

or

2. Start the collection asynchronously and return an acknowledgement immediately.

For a longer-running autonomous routine, asynchronous execution is likely to provide a cleaner architecture.

For example:

```text
Web Interface
     |
     | Start automated imaging
     v
FarmBot OS
     |
     | Immediate acknowledgement
     v
Interface

Meanwhile:

FarmbotOS.PhotoCollection
     |
     +--> Move to plant 1
     |
     +--> Capture image
     |
     +--> Move to plant 2
     |
     +--> Capture image
     |
     +--> ...
     |
     +--> Mark operation complete
```

This prevents the user-interface request from remaining blocked for the entire duration of physical robot execution.

---

## 12. Current Implementation Status

### 12.1 Confirmed Working

The following functionality has been demonstrated:

* Local FarmBot Web App deployment.
* Local Rails API.
* Local PostgreSQL database.
* Local MQTT/message-broker integration.
* FarmBot OS built from local source.
* Custom FarmBot OS firmware generation.
* Firmware deployment to Raspberry Pi 4.
* FarmBot network configuration through Ethernet.
* FarmBot configuration against the local API.
* FarmBot authentication against the local environment.
* Browser-to-message-broker communication.
* FarmBot-to-message-broker communication.
* FarmBot-to-local-web-app communication.
* Raspberry Pi-to-Farmduino communication.
* Physical FarmBot movement.
* Camera detection.
* Physical image capture.
* Invocation of the custom automated-imaging path through the modified interface.
* Complete connectivity reaching FarmBot connectivity code `31`.

### 12.2 Implemented and Under Active Testing

The following components exist but still require cleanup and validation:

* `FarmbotOS.PhotoCollection`.
* Plant-source integration.
* Automated imaging Lua integration.
* Automated imaging frontend.
* Experiment result reporting.
* Full autonomous multi-plant collection sequence.

### 12.3 Known Current Issues

1. Experiment errors represented as Elixir tuples are not JSON serializable by the current interface return path.

2. `PhotoCollection.run_now` currently encounters a five-second `GenServer.call` timeout during physical execution.

3. The automated imaging workflow requires final cleanup and repeatability testing before it should be considered stable.

4. The local development configuration is currently tied to the development laptop's `10.42.0.1` network configuration and should eventually be parameterized or clearly documented for replication on another development machine.

---

## 13. Current Repository State

### 13.1 FarmBot Web App

Current base:

```text
Repository: farmbot_web_app
Branch: staging
Commit: 5796fb3ac
Tag: v15.30.1
```

Modified files:

```text
app/controllers/api/tokens_controller.rb
app/lib/rmq_config_writer.rb
app/lib/session_token.rb
config/application.rb
frontend/__test_support__/fake_camera_data.ts
frontend/devices/actions.ts
frontend/photos/interfaces.ts
frontend/photos/photos.tsx
frontend/photos/reducer.ts
```

New directory:

```text
frontend/photos/automated_imaging/
```

### 13.2 FarmBot OS

Current base:

```text
Repository: farmbot_os
Branch: staging
Commit: 65b5c05d
Version: v15.5.2
```

Modified files:

```text
.tool-versions
config/target.exs
lib/farmbot_os.ex
lib/firmware/uart_detector.ex
lib/os/configurator/config_data_layer.ex
lib/os/configurator/supervisor.ex
lib/os/lua.ex
```

New files/directories:

```text
lib/experiments/
lib/os/lua/automated_imaging.ex
lib/photo_collection.ex
test/os/lua/ext/automated_imaging_test.exs
```

---

## 14. Immediate Next Steps

The project has moved beyond the primary infrastructure stage.

The immediate development priorities are:

1. Normalize experiment return values into JSON-safe structures.
2. Correct the synchronous execution timeout or transition the imaging routine to asynchronous execution.
3. Verify plant retrieval from the live FarmBot data source.
4. Execute a complete physical multi-plant imaging sequence.
5. Verify successful image creation and visibility through the modified interface.
6. Add appropriate experiment state and user feedback for running, completed, and failed operations.
7. Perform repeated physical tests to establish repeatability.
8. Clean the current source modifications.
9. Document which source modifications are essential and which are development-specific.
10. Parameterize or clearly document local network configuration.

---

## 15. Longer-Term Development Direction

With the local development infrastructure operational, future work can focus primarily on precision-agriculture functionality rather than platform bring-up.

The automated imaging experiment provides a foundation for higher-level routines such as:

* Scheduled plant monitoring.
* Repeated image collection from fixed plant locations.
* Configurable imaging intervals.
* Plant-specific monitoring routines.
* Image-history comparison.
* Integration of image-analysis models.
* Plant-health monitoring.
* Autonomous responses based on collected observations.

The intended architecture keeps physical hardware execution inside FarmBot OS while exposing configuration and control through the FarmBot Web App.

Conceptually:

```text
User
 |
 v
FarmBot Web Interface
 |
 | Configure desired behavior
 v
FarmBot OS
 |
 | Execute autonomous routine
 v
Physical FarmBot
 |
 | Collect observations
 v
Images / Sensor Data
 |
 v
Web Interface / Analysis
```

This preserves the existing FarmBot interaction model while allowing more sophisticated autonomous behavior to be added underneath it.

---

## 16. Development Milestone

The principal milestone reached during this phase is the transition from a partially simulated development environment to a physically integrated FarmBot development platform.

The project now supports modification of:

```text
Web Interface
      +
Local Server / API
      +
Message Broker
      +
FarmBot OS
      +
Custom Robot Logic
      +
Physical FarmBot Hardware
```

as one development environment.

The remaining automated-imaging issues are application-level implementation problems rather than blockers in the underlying FarmBot development infrastructure.

This provides the foundation from which additional precision-agriculture routines can be implemented, exposed through the user interface, and evaluated on the physical FarmBot.

---

## 17. Documentation Still To Be Completed

This notebook documents the current development state and the major steps that led to it.

The complete project documentation package should additionally contain:

```text
docs/
├── development_notebook.md
├── replication_guide.md
├── architecture.md
└── implementation_status.md
```

### `development_notebook.md`

Documents the development process, discoveries, problems encountered, debugging history, and major milestones.

### `replication_guide.md`

Provides a clean procedure for reproducing the development environment from a fresh machine and FarmBot.

### `architecture.md`

Describes the responsibilities and communication paths between:

* FarmBot Web App.
* Rails API.
* PostgreSQL.
* RabbitMQ.
* FarmBot OS.
* Lua extensions.
* Custom experiment modules.
* Raspberry Pi.
* Farmduino.
* Camera and physical hardware.

### `implementation_status.md`

Provides a concise snapshot of:

* Working functionality.
* Experimental functionality.
* Known issues.
* Required cleanup.
* Immediate next steps.
* Potential future extensions.

---

## 18. Source Inspection Required Before Final Replication Guide

Before finalizing the replication guide and architecture documentation, the current implementation of the custom modules should be inspected directly.

### FarmBot OS Inspection

Run from:

```bash
cd ~/farmbot-dev/farmbot_os
```

Then collect:

```bash
printf '\n===== PHOTO COLLECTION =====\n'
cat lib/photo_collection.ex

printf '\n===== PLANT SOURCE =====\n'
cat lib/experiments/photo_collection/plant_source.ex

printf '\n===== AUTOMATED IMAGING LUA =====\n'
cat lib/os/lua/automated_imaging.ex

printf '\n===== LUA MODIFICATIONS =====\n'
git diff -- lib/os/lua.ex

printf '\n===== SUPERVISION =====\n'
git diff -- \
  lib/farmbot_os.ex \
  lib/os/configurator/supervisor.ex

printf '\n===== CONFIGURATOR =====\n'
git diff -- \
  lib/os/configurator/config_data_layer.ex
```

### FarmBot Web App Inspection

Run from:

```bash
cd ~/farmbot-dev/farmbot_web_app
```

First list the automated imaging implementation:

```bash
printf '\n===== AUTOMATED IMAGING FILES =====\n'
find frontend/photos/automated_imaging -type f -print
```

Then inspect the frontend changes:

```bash
printf '\n===== FRONTEND DIFF =====\n'
git diff -- \
  frontend/devices/actions.ts \
  frontend/photos/interfaces.ts \
  frontend/photos/photos.tsx \
  frontend/photos/reducer.ts \
  frontend/photos/automated_imaging
```

Finally, inspect the local-server modifications:

```bash
printf '\n===== LOCAL SERVER DIFF =====\n'
git diff -- \
  app/controllers/api/tokens_controller.rb \
  app/lib/rmq_config_writer.rb \
  app/lib/session_token.rb \
  config/application.rb
```

These outputs will allow the final documentation to distinguish between:

* Changes required for local FarmBot operation.
* Changes required specifically for automated imaging.
* Temporary development modifications.
* Hardware-specific modifications.
* Configuration that should be moved to environment variables or setup instructions.
* Changes that should ultimately be cleaned up or upstreamed.

The replication guide should only be finalized after this distinction has been made.
