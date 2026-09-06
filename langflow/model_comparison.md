# Which model the assistant runs on, measured

Run by `langflow/build/compare_models.py` on 2026-09-06 09:31, against the live store
(open incident `ARK-INC-00139`, closed incident `ARK-INC-00131`).

Every check is mechanical. What they cannot see is whether the prose is any good;
the transcripts below are there to be read for that.

| Model | open incident, link and a grounded note | closed incident, no link | procedure, names where it is done | a filter the API does not take, handled quietly | outside the sources, refuses exactly | Total |
|---|---|---|---|---|---|---|
| `google/gemini-2.5-flash` | 3/3 | 3/3 | 3/3 | 3/3 | 2/2 | **14 of 14** |

## What each check failed on

**`google/gemini-2.5-flash`**: nothing failed.

## Transcripts

### `google/gemini-2.5-flash` - what is ARK-INC-00139 doing right now

_Branch: Incident Answer_

```text
Incident ARK-INC-00139 is new, with priority P3. It was raised 0 minutes ago. The summary is: Impeller cast_def_0_1638 flagged by visual inspection, defect probability 1.000 (operating point 0.0637). The assigned role is QC Engineer and it is assigned to P. Lindt (simulated operational context). The recommended action is to quarantine the part and log the defect against the batch.

You can make a move on this incident at http://192.168.178.100:8303/steering_cell?incident=ARK-INC-00139.

Suggested note: Acknowledged, Impeller cast_def_0_1638 flagged by visual inspection, defect probability 1.000 (operating point 0.0637), quarantining the part and logging the defect against the batch.
```

### `google/gemini-2.5-flash` - what is the status of ARK-INC-00131

_Branch: Incident Answer_

```text
Incident ARK-INC-00131 is closed. The summary is "Engine unit 111 of FD004 predicted RUL 21 cycles (priority threshold 25).". It was assigned to M. Brandt (Maintenance Planner) and closed by R. Ortiz (Quality Manager). The operational context is simulated.
```

### `google/gemini-2.5-flash` - how does an assignee acknowledge an incident, and where do they do it

_Branch: Procedure Answer_

```text
An assignee acknowledges an incident by moving its state from "new" to "acknowledged" on the cockpit's Steering Cell page. The acknowledgement window is 15 minutes for a P1 incident and 1 hour for a P2 incident, as detailed in the Arkon Project Charter and the Quality Steering Cell SOP. This action records the time of acknowledgement and the person who made it.

http://192.168.178.100:8303/steering_cell
```

### `google/gemini-2.5-flash` - which P1 incidents are open right now

_Branch: Incident Answer_

```text
There are no P1 incidents that are open right now.
```

### `google/gemini-2.5-flash` - what is the recall rate of the casting model on the night shift in building 4

_Branch: Procedure Answer_

```text
I do not have that in the Arkon sources available to me. Please raise it with the Quality Manager.
```

