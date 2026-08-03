# STATUS

## Badge applied for: **Artifacts Available**

We are applying for the **Artifacts Available** badge for the replication package accompanying:

> **Continuum: Automated Construction and Retrieval of Software Decision Knowledge Graphs from
> Developer-AI Conversations**
> Mohammad Ali Shehral, Karthik Ravi, Nikhil Trivedi, Akram Bayat
> 41st IEEE/ACM International Conference on Automated Software Engineering (ASE '26),
> Industry Showcase track. DOI: [10.1145/3832783.3834535](https://doi.org/10.1145/3832783.3834535)

## Justification

The ACM criterion for *Artifacts Available* is that author-created artifacts relevant to the paper have been
placed on a publicly accessible archival repository, with a DOI provided. This artifact meets that criterion:

- **Archived with a DOI.** A version-pinned snapshot is deposited on Zenodo, an archival repository
  independent of GitHub and of the authors' accounts:
  **[10.5281/zenodo.21770150](https://doi.org/10.5281/zenodo.21770150)** (version DOI, release
  `v1.0.2-ase-paper`). The concept DOI [10.5281/zenodo.21770149](https://doi.org/10.5281/zenodo.21770149)
  always resolves to the latest version. The Zenodo record is linked to the paper via an
  `isSupplementTo` related identifier.
- **Publicly accessible.** The record and its files are public, with no registration or request step. The
  development repository is also public at
  [github.com/shehral/continuum-ase-2026](https://github.com/shehral/continuum-ase-2026).
- **Openly licensed.** MIT (see `LICENSE`), permitting inspection, reuse, and redistribution.
- **Relevant to the paper.** The archive contains the system source, the evaluation corpus, the annotation
  and inter-annotator agreement data, the real-log case-study chunks, the canonical mapping dictionary, the
  evaluation scripts, and the cached result files backing every number reported in the paper. `README.md`
  maps each research question to its script and its result file.
- **Citation metadata included.** `CITATION.cff` carries the four authors with ORCID iDs, the license, the
  version, and the paper DOI.

## Badges not applied for, and why

We are **not** applying for *Artifacts Evaluated — Functional* or *Reusable* at this time. End-to-end
re-execution of the extraction and embedding stages depends on a third-party hosted service (the NVIDIA NIM
API) requiring reviewer-supplied credentials, and on a running PostgreSQL + Neo4j + Redis stack. Because that
dependency is outside our control and LLM inference is non-deterministic, we cannot guarantee a reviewer would
reproduce identical numbers within the evaluation window. We have instead committed the cached result files for
every reported number so that all claims can be **verified** from the archive without any external service; see
`README.md` § "Reproducing the paper's results".

## Scope and privacy note

Raw developer-AI conversation logs are not redistributed. The released Vibe Voyager case-study chunks are
scrubbed of personal identifiers, credentials, and third-party content. This is stated in the paper's Data
Availability Statement.
