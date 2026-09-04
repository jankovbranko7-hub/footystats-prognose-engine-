# V0.4.3 FULL-5 Production

Release architecture:

- V0.4.2 hybrid lambda retained as the stable base.
- Selective FULL-5 regularized Poisson strengthening using MatchDaten, LeagueDaten, FormDaten, TableDaten and PlayerDaten.
- Dixon-Coles score distribution retained with rho = -0.25.
- FULL-5 regularization locked to alpha = 3.0 after competition-grouped nested validation on 137 strict pre-match archives.
- Experimental Elite-Lambda correction is not included.
- Missing required FULL-5 core features fall back to unchanged V0.4.2 lambdas; no invented values.

Validation reference:

- 137 strict pre-match matches.
- FULL-5 improved aggregate probabilistic quality versus original V0.4.2 in the controlled comparison.
- Historical backtest results are development evidence, not a future guarantee.
