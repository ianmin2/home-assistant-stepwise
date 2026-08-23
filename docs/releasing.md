# Releasing

Phase 6, in the order it has to happen. Everything here needs a GitHub account,
which is why it is written down rather than done.

## Once, before the first release

### 1. The repository

```bash
gh auth login
gh repo create ianmin2/stepwise --public --source . --remote origin --push
```

HACS reads three things from the repository itself, and refuses without them:

- a **description** — "Guided step by step procedures for Home Assistant" does
- **topics**, including `home-assistant` and `hacs`
- a **README**, which is already here

```bash
gh repo edit ianmin2/stepwise \
  --description "Guided step by step procedures for Home Assistant" \
  --add-topic home-assistant --add-topic hacs --add-topic homeassistant \
  --add-topic home-assistant-custom --add-topic voice-assistant
```

### 2. The icon

Home Assistant serves integration icons from its own `brands` repository, and
custom integrations live under `custom_integrations/`. The two files are already
drawn, in [brands/custom_integrations/stepwise/](../brands/custom_integrations/stepwise):

| File | Size |
|---|---|
| `icon.png` | 256×256 |
| `icon@2x.png` | 512×512 |

They are a plain mark — three steps with a marker resting on the middle one —
and replacing them with something better is a file copy, not a code change.

```bash
gh repo fork home-assistant/brands --clone --remote
cd brands
git checkout -b add-stepwise
mkdir -p custom_integrations/stepwise
cp ../brands/custom_integrations/stepwise/icon*.png custom_integrations/stepwise/
git add custom_integrations/stepwise
git commit -m "Add Stepwise"
gh pr create --title "Add Stepwise" --body "Custom integration: https://github.com/ianmin2/stepwise"
```

The `brands/` directory in this repository is only a holding pen for those two
files. It is not part of the integration and Home Assistant never reads it.

## Every release

1. **Update the changelog.** Move `Unreleased` into a version heading with the
   date.
2. **Bump the version** in `custom_components/stepwise/manifest.json`. The
   release workflow refuses to publish if it disagrees with the tag, which is
   the point of it.
3. **Check it locally.**

   ```bash
   python3 -m unittest discover -s tests -p "test_*.py"
   ruff check custom_components tests
   ```

4. **Tag and release.**

   ```bash
   git tag -a v0.1.0 -m "Stepwise 0.1.0"
   git push origin main --tags
   gh release create v0.1.0 --title "Stepwise 0.1.0" --notes-file CHANGELOG.md
   ```

   Publishing the release runs the workflow, which checks the manifest against
   the tag and attaches `stepwise.zip` for people installing by hand.

## Installing it before it is listed

HACS does not need Stepwise to be in its default list. Anyone can add it now:

*HACS → three dots → Custom repositories →* `https://github.com/ianmin2/stepwise`,
category *Integration*.

Getting into the default list is a separate pull request to
`hacs/default`, and it wants the brands PR merged first.

## What is checked automatically

Every push runs [validate.yml](../.github/workflows/validate.yml):

- the test suite, on Python 3.13
- `ruff`
- Home Assistant's own **hassfest**, which validates the manifest
- the **HACS** validator, with `brands` ignored until that pull request lands

Take `ignore: brands` out of the workflow once the brands pull request is
merged, so a future rename is caught.
