# MAAS Paperclip-Leaning Mockup

This is a fresh standalone UI-only mockup for the MAAS product pivot.

It is intentionally:

- separate from the current MAAS frontend
- separate from the earlier failed mockups
- structured around the actual Paperclip app shell, not the Paperclip landing page
- darker, tighter, and more issue-first than the previous MAAS control-room experiments

The target is:

- MAAS as the control plane for autonomous organizations
- visually and structurally closer to the actual Paperclip app UI, not its landing page
- informed by Paperclip's matte dark product shell, list-first issue management, and dedicated object pages
- corrected away from the fake human-company org chart metaphor
- structurally informed by Linear-style issue detail behavior where it helps
- explicitly shows three organization states:
  - startup / initial activation
  - active execution at scale
  - resolving / recovery

Primary surfaces in this mockup:

- `Dashboard`
- `Inbox`
- `Issues`
- `Goals`
- `Agents`
- `Topology`

Key model choices:

- `Issues` are the center of the product
- `Resolved` work is visible and searchable, not hidden
- one issue can show multiple parallel agent threads
- issue detail includes a Git-like execution history rather than a flat comment dump
- `Topology` models capability pools, runtimes, output queues, and handoffs instead of a human org chart

## Open it

```bash
open /Users/bigcube/Desktop/repos/maas/mockups/org-control-plane-paperclip/index.html
```

Or serve it:

```bash
cd /Users/bigcube/Desktop/repos/maas/mockups/org-control-plane-paperclip
python3 -m http.server 4312
```

Then open:

`http://127.0.0.1:4312/`

## Goal

This mockup is meant to test:

- product framing
- hierarchy
- information architecture
- visual language
- believable operational volume and state transitions
- how MAAS should visualize AI-native coordination instead of human hierarchy

before any attempt to rebuild the real frontend.
