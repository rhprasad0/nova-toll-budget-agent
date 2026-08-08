# Evaluation plan: I-95/I-495 junction

The suite covers the reported Wolf Trap-to-Dumfries regression, the reverse southbound movement, and the historical both-directions-closed interval. It requires exact planner-derived tool calls, movement-specific Edsall/Franconia boundaries, no duplicate calls, and exact decimal addition of all returned fares into a **Known toll total** that excludes the unpriced junction.

The companion simulated-user suite challenges both easy-to-confuse boundaries and asks whether known fares may be summed without calling the gap free. Each conversation is capped at three turns; qualitative judging is submitted asynchronously by the nightly report pipeline.
