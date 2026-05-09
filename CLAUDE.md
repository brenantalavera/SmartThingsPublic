# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is the official SmartThings public repository of **SmartApps** and **Device Type Handlers** (DTHs) — Groovy code that runs on the SmartThings cloud / hub platform. It is not a standalone application; the Groovy files here are deployed to and executed by the SmartThings runtime. Most "running" of code happens in the SmartThings IDE / simulator (https://ide.smartthings.com), not locally.

## Build & Verify

The project uses Gradle (wrapper included) with the Groovy plugin. Build tasks require Artifactory credentials passed as Gradle properties — without them, dependency resolution will fail.

```bash
# Resolve dependencies (mirrors what CI does first)
./gradlew dependencies \
  -PsmartThingsArtifactoryUserName="$ARTIFACTORY_USERNAME" \
  -PsmartThingsArtifactoryPassword="$ARTIFACTORY_PASSWORD"

# Compile both source sets — this is the primary "does it build" check
./gradlew compileSmartappsGroovy compileDevicetypesGroovy \
  -PsmartThingsArtifactoryUserName="$ARTIFACTORY_USERNAME" \
  -PsmartThingsArtifactoryPassword="$ARTIFACTORY_PASSWORD"

# Compile just one source set
./gradlew compileSmartappsGroovy   -P...
./gradlew compileDevicetypesGroovy -P...
```

There is **no test suite** in this repo (`circle.yml` literally echoes "We don't have any tests :-("). Do not invent test commands. Verification = the Groovy files compile, plus manual testing in the SmartThings IDE/simulator.

CI is CircleCI 1.0 (`circle.yml`), Oracle JDK 8. Deployment to S3 happens automatically on the `master` (dev), `staging`, and `production` branches via the `smartthings-executable-deployment` Gradle plugin — do not run `deployArchives` locally.

## Source Layout & Naming Conventions

Two top-level source roots, wired up as Gradle source sets in `build.gradle`:

- `smartapps/<namespace>/<app-name>.src/<app-name>.groovy` — user-facing automations (e.g. "Big Turn On", "Good Night")
- `devicetypes/<namespace>/<device-name>.src/<device-name>.groovy` — handlers that talk to physical devices (Z-Wave, ZigBee, LAN, cloud)

Hard rules enforced by the SmartThings platform:

- **Each handler lives in its own `<name>.src/` directory** containing exactly one Groovy file of the same base name. The `.src` suffix is required by the IDE's GitHub integration.
- **The `<namespace>` directory must match the `namespace:` field** inside the file's `definition(...)` / `metadata.definition(...)` block. The SmartThings namespace is `smartthings`; community contributors use their own (`com-obycode`, `dianoga`, vendor names, etc.). When adding a new app/device, pick the directory that matches the `namespace` you set, or create a new one.
- File names are lower-kebab-case; `name:` inside the file is human-readable Title Case.

Special directories:

- `devicetypes/capabilities/*-capability.src/` — minimal stub handlers (one per capability) used as reference/templates. Touch these only when adding a brand-new capability example.
- `smartapps/smartthings/examples/every-element.src/` — kitchen-sink demo of every preference UI element. Useful as a reference when building preference pages.

## SmartApp vs. Device Handler Anatomy

These are similar but **not interchangeable** — they target different runtime APIs.

**SmartApp** (`smartapps/...`) — orchestrates devices and reacts to events:
```
definition(name, namespace, author, description, category, iconUrl, iconX2Url)
preferences { section(...) { input "name", "capability.xxx", ... } }
def installed()  { subscribe(...) }   // first install
def updated()    { unsubscribe(); subscribe(...) }  // settings changed
def <handler>(evt) { ... }            // event callbacks
```
Common pattern: `updated()` always calls `unsubscribe()` before re-subscribing — preserve this when editing.

**Device Type Handler** (`devicetypes/...`) — drives one physical device:
```
metadata {
    definition(name, namespace, author, ...) {
        capability "Switch"
        fingerprint deviceId: "...", inClusters: "..."   // protocol matching
    }
    simulator { status "..." : "..."; reply "..." : "..." }
    tiles     { standardTile(...) { state "..." } main "..." details [...] }
}
def parse(String description) { ... }   // inbound protocol frames -> events
def on()  / def off() / def refresh()    // capability commands
```
Tiles are the legacy mobile UI; `multiAttributeTile` is the newer richer variant. `fingerprint` lines are how the hub auto-pairs a device — be very careful editing them.

When in doubt about which APIs are available inside a handler, check the SmartThings docs (http://docs.smartthings.com); the runtime API is not represented in source here.

## Editing Existing Handlers — Things to Watch For

- **Preserve the Apache 2.0 license header** at the top of every file; existing files all carry it.
- **Don't change `namespace:` or `name:`** on an existing published handler — these are the identity by which the platform tracks installed instances.
- **`runLocally: true` / `executeCommandsLocally`** flags on a `definition` mean the handler runs on-hub. Don't toggle these without understanding the consequences.
- **`fingerprint` entries** define automatic device discovery — adding/removing them affects which physical devices auto-pair to this handler.
- Many handlers depend on `parent`/`child` relationships (composite devices). If a handler creates child devices, the corresponding child handler must also exist in `devicetypes/`.
- Groovy version is pinned to **2.4.7**; avoid syntax that requires newer Groovy.

## Deployment Branches

`master` → dev, `staging` → staging, `production` → prod. CircleCI auto-deploys on push. Do not push directly to these branches without coordination.
