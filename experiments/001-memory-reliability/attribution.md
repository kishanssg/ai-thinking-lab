# Research attribution

Jianhua Jiang, Dongbo Yuan, and Weihua Li. *MemRiskBench: Trace-Aware Risk-Preserving Evaluation for Long-Horizon LLM Agents*. arXiv:2609.14976v1, submitted September 14, 2026.

Sources: [arXiv record](https://arxiv.org/abs/2609.14976v1) and [full text](https://arxiv.org/html/2609.14976v1), checked September 20, 2026. The record identifies an arXiv preprint; it does not list a journal or conference publication. We do not assert peer-reviewed acceptance.

The paper studies failures involving persistent memory and describes deterministic scoring of recorded behavior. Section 3.1 discusses acting on information superseded by an update; Sections 4 and 6 describe a 120-episode evaluation involving five locally run quantized models. Those are the authors' experiment and claims, not ours. We have not independently reproduced their results or verified their released artifact licenses.

Our contribution is an independently implemented Python/SQLite assignment simulation. Its six fixtures, policies, tests, result tables, and event logs belong to this experiment; none were imported from the paper's benchmark. We evaluate an application-level mechanism without running an LLM. We do not reproduce the benchmark, scores, or subset-selection method, and imply no author endorsement.

The citation supplies research context. No paper passages, figures, code, or datasets are reproduced here beyond bibliographic identification and a short original summary. The arXiv full text displays an arXiv non-exclusive distribution license, not a blanket permission for us to relicense its contents. GitHub Actions references GitHub-maintained checkout and Python setup actions; their source is not vendored in this repository.
