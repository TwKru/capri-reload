# SPDX-License-Identifier: Apache-2.0
# Adapted from hexgrad/misaki, misaki/espeak.py, revision fba1236595f2d2bf21d414ba6e57d25256afada3.
# Changes: include only the EspeakG2P class; dependencies are already provided by kokoro-onnx.
# See LICENSE-MISAKI.txt for the original copyright and license.
from phonemizer.backend.espeak.wrapper import EspeakWrapper
from typing import Tuple
import espeakng_loader
import phonemizer
import re

EspeakWrapper.set_library(espeakng_loader.get_library_path())
EspeakWrapper.set_data_path(espeakng_loader.get_data_path())

class EspeakG2P:
    def __init__(self, language, version=None):
        self.language = language
        self.version = version
        self.backend = phonemizer.backend.EspeakBackend(
            language=language, preserve_punctuation=True, with_stress=True,
            tie='^', language_switch='remove-flags'
        )
        self.e2m = {
            'a^ɪ':'I', 'a^ʊ':'W',
            'd^z':'ʣ', 'd^ʒ':'ʤ',
            'e^ɪ':'A',
            'o^ʊ':'O', 'ə^ʊ':'Q',
            's^s':'S',
            't^s':'ʦ', 't^ʃ':'ʧ',
            'ɔ^ɪ':'Y',
        }
        if version == '2.0':
            self.e2m.update({
                'œ̃':'B', 'ɔ̃':'C', 'ɑ̃':'D', 'ɛ̃':'E',
                'ʊ̃':'V', 'ũ':'U', 'õ':'X', 'ɐ̃':'Z',
            })
        self.e2m = sorted(self.e2m.items())

    def __call__(self, text) -> Tuple[str, None]:
        # Angles to curly quotes
        text = text.replace('«', chr(8220)).replace('»', chr(8221))
        # Parentheses to angles
        text = text.replace('(', '«').replace(')', '»')
        ps = self.backend.phonemize([text])
        if not ps:
            return '', None
        ps = ps[0].strip()
        for old, new in self.e2m:
            ps = ps.replace(old, new)
        # Delete any remaining tie characters, hyphens (not sure what they mean)
        ps = ps.replace('^', '')
        if self.version == '2.0':
            ps = ps.replace(chr(809), '').replace(chr(810), '')
            ps = re.sub(r'(\S)\u0329', r'ᵊ\1', ps)
        else:
            ps = ps.replace('-', '')
        # Angles back to parentheses
        ps = ps.replace('«', '(').replace('»', ')')
        return ps, None
