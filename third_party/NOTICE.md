# Kokoro Russian pronunciation helpers

`kokoro_ru_frontend.py` is adapted from zaakirio/kokoro-ru, `ru_g2p.py`,
revision d649c57b239b18c4c384378127cbf01dba039bc1.
Source: https://huggingface.co/zaakirio/kokoro-ru
Upstream declares code Apache-2.0 and model weights OpenRAIL.
Changes: keep only pure pronunciation functions. Capri uses eSpeak dictionary stress,
without loading the optional RUAccent neural models. Model weights are downloaded separately.
See LICENSE-APACHE-2.0.txt for the code license.

`misaki_espeak.py` contains the EspeakG2P class from hexgrad/misaki, revision fba1236595f2d2bf21d414ba6e57d25256afada3.
Source: https://github.com/hexgrad/misaki . Apache-2.0 license: LICENSE-MISAKI.txt.
Changes: omit the unused English fallback class; keep the non-English frontend only.
