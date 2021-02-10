External repository for Bitcoin Core related maintenance tools.

github-merge
------------

A small script to automate merging pull-requests securely and sign them with GPG.

For example:

```bash
./github-merge.py 1234
```

(in any git repository) will help you merge pull request #1234 for the configured repository.

What it does:
* Fetch master and the pull request.
* Locally construct a merge commit.
* Show the diff that merge results in.
* Ask you to verify the resulting source tree (so you can do a make check or whatever).
* Ask you whether to GPG sign the merge commit.
* Ask you whether to push the result upstream.

This means that there are no potential race conditions (where a
pull request gets updated while you're reviewing it, but before you click
merge), and when using GPG signatures, that even a compromised GitHub
couldn't mess with the sources.

### Setup

Configuring the github-merge tool for the bitcoin repository is done in the following way:

    git config githubmerge.repository bitcoin/bitcoin
    git config githubmerge.testcmd "make -j4 check" (adapt to whatever you want to use for testing)
    git config --global user.signingkey mykeyid

If you want to use HTTPS instead of SSH for accessing GitHub, you need set the host additionally:

    git config githubmerge.host "https://github.com"  (default is "git@github.com", which implies SSH)

### Authentication (optional)

The API request limit for unauthenticated requests is quite low, but the
limit for authenticated requests is much higher. If you start running
into rate limiting errors it can be useful to set an authentication token
so that the script can authenticate requests.

- First, go to [Personal access tokens](https://github.com/settings/tokens).
- Click 'Generate new token'.
- Fill in an arbitrary token description. No further privileges are needed.
- Click the `Generate token` button at the bottom of the form.
- Copy the generated token (should be a hexadecimal string)

Then do:

    git config --global user.ghtoken "pasted token"

### Create and verify timestamps of merge commits

To create or verify timestamps on the merge commits, install the OpenTimestamps
client via `pip3 install opentimestamps-client`. Then, download the gpg wrapper
`ots-git-gpg-wrapper.sh` and set it as git's `gpg.program`. See
[the ots git integration documentation](https://github.com/opentimestamps/opentimestamps-client/blob/master/doc/git-integration.md#usage)
for further details.

verify-commits
--------------

Script to verify signatures and tree hashes of all commits made with the `github-merge.py`
script.

See the [README](verify-commits/README.md) for more details.

backport
--------

Script to backport pull requests in order of merge, to minimize number of conflicts.
Pull ids are listed in `to_backport.txt` or given on the command line.

Requires `pip3 install gitpython` or similar.

treehash512
--------------

This script will show the SHA512 tree has for a certain commit, or HEAD
by default.

Usage:

```bash
treehash512.py [<commithash>]
```

This should match the Tree-SHA512 commit metadata field added by
github-merge.

signoff
----------

This is an utility to manually add a treehash to the HEAD commit and then
gpg-sign it. This is useful when there is the need to manually add a commit.

Usage:

```bash
signoff.py
```
(no command line arguments)

When there is already a treehash on the HEAD commit, it is compared against
what is computed. If this matches, it continues. If the treehash mismatches an
error is thrown. If there is no treehash it adds the "Tree-SHA512:" header with
the computed hash to the commit message.

After making sure the treehash is correct it verifies whether the commit is
signed. If so it just displays the signature, if not, it is signed.

list-pulls
----------

Script to parse git commit list, extract github issues to create a changelog in
text and json format.

Run this in the root directory of the repository.

This requires an up-to-date checkout of https://github.com/zw/bitcoin-gh-meta.git
in the parent directory, or environment variable `GHMETA`.

It takes a range of commits and a .json file of PRs to exclude, for
example if these are already backported in a minor release. This can be the pulls.json
generated from a previous release.

Example usage:

    ../maintainer-tools/list-pulls.py v0.18.0 0.19 relnot/pulls-exclude.json > relnot/pulls.md

The output of this script is a first draft based on rough heuristics, and
likely needs to be extensively manually edited before ending up in the release
notes.

make-tag
--------

Make a new release tag, performing a few checks.

Usage: `make-tag.py <tag>`.

gitian-verify
-------------

A script to verify gitian deterministic build signatures for a release in one
glance. It will print a matrix of signer versus build package, and a list of
missing keys.

To be able to read gitian's YAML files, it needs the `pyyaml` module. This can
be installed from pip, for example:

```bash
pip3 install pyyaml
```
(or install the distribution package, in Debian/Ubuntu this is `python3-yaml`)

Example usage: `./gitian-verify.py -r 0.21.0rc5 -d ../gitian.sigs -k ../bitcoin/contrib/gitian-keys/keys.txt`

Where

- `-r 0.21.0rc5` specifies the release to verify signatures for.
- `-d ../gitian.sigs` specifies the directory where the repository with signatures, [gitian.sigs](https://github.com/bitcoin-core/gitian.sigs/) is checked out.
- `../bitcoin/contrib/gitian-keys/keys.txt` is the path to `keys.txt` file inside the main repository that specifies the valid keys and what signers they belong to.

Example output:
```
Signer            linux      osx-unsigned  win-unsigned   osx-signed    win-signed
justinmoon        No Key        No Key        No Key        No Key        No Key
laanwj              OK            OK            OK            OK            OK
luke-jr             OK            OK            OK            OK            OK
marco               -             OK            OK            OK            OK

Missing keys
norisg         3A51FF4D536C5B19BE8800A0F2FC9F9465A2995A  from GPG, from keys.txt
...
```

See `--help` for the full list of options and their descriptions.

The following statuses can be shown:

- `Ok` Full match.
- `No key` Signer name/key combination not in keys.txt, or key not known to GPG (which one of these it is, or both, will be listed under "Missing keys").
- `Bad` Known key but invalid PGP signature.
- `Mismatch`Correct PGP signature but mismatching binaries.
