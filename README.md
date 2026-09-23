# Persistent-Fable

Response-signature enforcement plus Outcome Gate, a free static web harness for frozen real-world objectives, execution evidence, and shadow runtime v4.2 discovery.

- **Open the web app:** [Outcome Gate](https://keepinitkrispy.github.io/Persistent-Fable/fable-enforce/web/)
- **Read setup and limits:** [fable-enforce/WEB_HARNESS.md](fable-enforce/WEB_HARNESS.md)
- **Use the existing response filter:** `python3 fable-enforce/scripts/filter.py --test`
- **Run the outcome gate checks:** `python3 fable-enforce/scripts/objective_gate.py --test`

The app is static and does not send objective records to a server. Each browser stores its own state until you export and transfer a snapshot. Claude Code enforcement is project scoped and activates when you place an exported active record at `.fable/active_objective.json`; the file is gitignored.
