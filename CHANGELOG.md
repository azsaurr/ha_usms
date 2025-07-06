## v0.4.2 (2025-07-06)

## v0.4.1 (2025-06-07)

### Fix

- ensure pd.Timestamp objects are converted to datetime objects in the same timezone
- update usms depencency to v0.9.2

## v0.4.0 (2025-06-03)

### Feat

- add next_refresh as an extra attribute to the meter sensor entity
- add option to configure custom poll interval
- automatically attempt to download missing statistics when polling for updates
- add button to download consumptions data for days with missing or incomplete statistics

### Fix

- pre-import tzdata to avoid blocking call in async context warning
- adapt code to usms v0.9.1 and integrate dependency injection of async httpx client
- remove unnecessary listener and handler, causing intergration to be reloaded twice on options change

## v0.3.0 (2025-04-26)

### Perf

- speed up data update process by reducing number of requests and skipping rarely changed data

## v0.2.3 (2025-04-23)

### Fix

- move return statement that was misplaced inside an except statement, causing it to not be executed and the method returning None

## v0.2.2 (2025-04-23)

### Fix

- move misplaced return statement that caused early exit

## v0.2.1 (2025-04-23)

## v0.2.0 (2025-04-19)

## v0.1.1 (2025-04-18)

### Feat

- **core**: add initial working source code

### Fix

- added missing property decorator and fix typo in attribute name
