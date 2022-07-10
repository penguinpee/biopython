# Copyright 2022 by Michiel de Hoon.  All rights reserved.
#
# This file is part of the Biopython distribution and governed by your
# choice of the "Biopython License Agreement" or the "BSD 3-Clause License".
# Please see the LICENSE file that should have been included as part of this
# package.
"""Bio.Align support for hhr files generated by HHsearch or HHblits in HH-suite.

This module provides support for output in the hhr file format generated by
HHsearch or HHblits in HH-suite.

You are expected to use this module via the Bio.Align functions.
"""
import numpy


from Bio.Align import Alignment
from Bio.Align import interfaces
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio import BiopythonExperimentalWarning

from collections import defaultdict

import warnings

warnings.warn(
    "Bio.Align.hhr is an experimental module which may undergo "
    "significant changes prior to its future official release.",
    BiopythonExperimentalWarning,
)


class AlignmentIterator(interfaces.AlignmentIterator):
    """Alignment iterator for hhr output files generated by HHsearch or HHblits.

    HHsearch and HHblits are part of the HH-suite of programs for Hidden Markov
    Models. An output files in the hhr format contains multiple pairwise
    alignments for a single query sequence.
    """

    def __init__(self, source):
        """Create an AlignmentIterator object.

        Arguments:
         - source   - input data or file name

        """
        super().__init__(source, mode="t", fmt="hhr")

    def _read_header(self, stream):
        metadata = {}
        for line in stream:
            line = line.strip()
            if line == "":
                break
            key, value = line.split(None, 1)
            if key == "Query":
                self.query_name = value
            elif key == "Match_columns":
                metadata[key] = int(value)
            elif key == "No_of_seqs":
                value1, value2 = value.split(" out of ")
                metadata[key] = (int(value1), int(value2))
            elif key in ("Neff", "Template_Neff"):
                metadata[key] = float(value)
            elif key == "Searched_HMMs":
                metadata[key] = int(value)
            elif key == "Date":
                metadata["Rundate"] = value
            elif key == "Command":
                metadata["Command line"] = value
            else:
                raise ValueError("Unknown key '%s'" % key)
        self.metadata = metadata
        try:
            line = next(stream)
        except StopIteration:
            raise ValueError("Truncated file.") from None
        assert line.split() == [
            "No",
            "Hit",
            "Prob",
            "E-value",
            "P-value",
            "Score",
            "SS",
            "Cols",
            "Query",
            "HMM",
            "Template",
            "HMM",
        ]
        number = 0
        for line in stream:
            if line.strip() == "":
                break
            number += 1
            word, _ = line.split(None, 1)
            assert int(word) == number
        self._number = number
        self._counter = 0

    def _read_next_alignment(self, stream):
        def create_alignment():
            n = len(target_sequence)
            assert len(query_sequence) == n
            if n == 0:
                return
            coordinates = Alignment.infer_coordinates([target_sequence, query_sequence])
            coordinates[0, :] += target_start
            coordinates[1, :] += query_start
            sequence = {query_start: query_sequence.replace("-", "")}
            query_seq = Seq(sequence, length=query_length)
            query = SeqRecord(query_seq, id=self.query_name)
            sequence = {target_start: target_sequence.replace("-", "")}
            target_seq = Seq(sequence, length=target_length)
            target_annotations = {
                "hmm_name": hmm_name,
                "hmm_description": hmm_description,
            }
            target = SeqRecord(
                target_seq, id=target_name, annotations=target_annotations
            )
            fmt = f"{' ' * target_start}%-{target_length - target_start}s"
            target.letter_annotations["Consensus"] = fmt % target_consensus.replace(
                "-", ""
            )
            target.letter_annotations["ss_pred"] = fmt % target_ss_pred.replace("-", "")
            target.letter_annotations["ss_dssp"] = fmt % target_ss_dssp.replace("-", "")
            target.letter_annotations["Confidence"] = fmt % confidence.replace(" ", "")
            fmt = f"{' ' * query_start}%-{query_length - query_start}s"
            query.letter_annotations["Consensus"] = fmt % query_consensus.replace(
                "-", ""
            )
            query.letter_annotations["ss_pred"] = fmt % query_ss_pred.replace("-", "")
            records = [target, query]
            alignment = Alignment(records, coordinates=coordinates)
            alignment.annotations = alignment_annotations
            alignment.column_annotations = {}
            alignment.column_annotations["column score"] = column_score
            return alignment

        query_start = None
        query_sequence = ""
        query_consensus = ""
        query_ss_pred = ""
        target_start = None
        target_sequence = ""
        target_consensus = ""
        target_ss_pred = ""
        target_ss_dssp = ""
        column_score = ""
        confidence = ""
        for line in stream:
            line = line.rstrip()
            if not line:
                pass
            elif line.startswith(">"):
                hmm_name, hmm_description = line[1:].split(None, 1)
                line = next(stream)
                words = line.split()
                alignment_annotations = {}
                for word in words:
                    key, value = word.split("=")
                    if key == "Aligned_cols":
                        continue  # can be obtained from coordinates
                    if key == "Identities":
                        value = value.rstrip("%")
                    value = float(value)
                    alignment_annotations[key] = value
            elif line == "Done!":
                try:
                    next(stream)
                except StopIteration:
                    pass
                else:
                    raise ValueError(
                        "Found additional data after 'Done!'; corrupt file?"
                    )
            elif line.startswith(" "):
                column_score += line.strip()
            elif line.startswith("No "):
                counter = self._counter
                self._counter += 1
                key, value = line.split()
                assert int(value) == self._counter
                if self._counter > self._number:
                    raise ValueError(
                        "Expected %d alignments, found %d"
                        % (self._number, self._counter)
                    )
                if counter > 0:
                    return create_alignment()
            elif line.startswith("Confidence"):
                key, value = line.split(None, 1)
                confidence += value
            elif line.startswith("Q ss_pred "):
                key, value = line.rsplit(None, 1)
                query_ss_pred += value
            elif line.startswith("Q Consensus "):
                key1, key2, start, consensus, end, total = line.split()
                start = int(start) - 1
                end = int(end)
                assert total.startswith("(")
                assert total.endswith(")")
                total = int(total[1:-1])
                query_consensus += consensus
            elif line.startswith("Q "):
                key1, key2, start, sequence, end, total = line.split()
                assert self.query_name.startswith(key2)
                start = int(start) - 1
                end = int(end)
                assert total.startswith("(")
                assert total.endswith(")")
                query_length = int(total[1:-1])
                assert query_length == self.metadata["Match_columns"]
                if query_start is None:
                    query_start = start
                query_sequence += sequence
            elif line.startswith("T ss_pred "):
                key, value = line.rsplit(None, 1)
                target_ss_pred += value
            elif line.startswith("T ss_dssp "):
                key, value = line.rsplit(None, 1)
                target_ss_dssp += value
            elif line.startswith("T Consensus "):
                key1, key2, start, consensus, end, total = line.split()
                start = int(start) - 1
                end = int(end)
                assert total.startswith("(")
                assert total.endswith(")")
                total = int(total[1:-1])
                target_consensus += consensus
            elif line.startswith("T "):
                key, name, start, sequence, end, total = line.split()
                assert key == "T"
                target_name = name
                start = int(start) - 1
                end = int(end)
                assert total.startswith("(")
                assert total.endswith(")")
                target_length = int(total[1:-1])
                if target_start is None:
                    target_start = start
                target_sequence += sequence
            else:
                raise ValueError("Failed to parse line '%s...'" % line[:30])
        alignment = create_alignment()
        number = self._number
        counter = self._counter
        if number == counter:
            self._close()
            del self._number
            del self._counter
        if alignment is None and number > 0:
            raise ValueError("Expected %d alignments, found %d" % (number, counter))
        return alignment
