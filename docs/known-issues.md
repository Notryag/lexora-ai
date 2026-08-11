# Known Issues

## KI-001: Relationship-overlap answers repeat resolved or strongly implied questions

Status: recorded, not fixed in the dataset-normalization slice.

Reproduction input:

> 我的情况是这样的，我女朋友结婚了，但是已经和她老公分居好几年，是不是算自动离婚了？
> 我们没以夫妻的名义同居算重婚吗？

Observed problems:

- the answer opens with an unnecessary mainland-China qualification for this product context;
- it answers that separation does not automatically dissolve marriage, then asks whether a formal
  divorce already occurred even though the user's framing strongly implies the opposite;
- it repeats hypotheticals and follow-up dimensions contrary to the stated fact that the parties do
  not hold themselves out as spouses;
- no reviewed case-law card is shown, so the answer relies only on statutes and general caution.

Likely boundary issue:

- the current preparation contract records only facts stated explicitly and has no separate state for
  facts directly entailed by ordinary-language framing;
- the tool-level regression test verifies only that an explicitly denied factor is not re-asked; it
  does not verify the final answer or redundant unknown factors;
- guiding-case retrieval is optional and the currently reviewed corpus may not cover this issue.

Acceptance criteria for the later conversation-quality slice:

1. answer the automatic-divorce question directly without re-asking whether separation itself ended
   the marriage;
2. do not ask about facts already stated, denied, or directly entailed by the user's framing;
3. do not introduce contrary hypotheticals unless they are necessary to explain a material boundary;
4. test the final streamed answer, not only the preparation-tool payload;
5. show a case-law card only when an actually retrieved, reviewed case is cited; never fabricate one.
