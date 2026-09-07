"""V1 probability initialization note.

The first V1 standalone build intentionally starts from the previously validated
40-feature coefficient set as a numerical seed so independence of code ownership
does not mean throwing away validated calibration. V1 does not import or execute
`v043_engine` at runtime. New FULL-DATA weights require their own OOS validation.
"""
