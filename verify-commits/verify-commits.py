#!/usr/bin/env python3
# Copyright (c) 2018-2019 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Verify commits against a trusted keys list."""
import argparse
import hashlib
import os
import subprocess
import sys
import time

GIT = os.getenv('GIT', 'git')

def git_show_parents_hashes(commit):
    return subprocess.check_output([GIT, 'show', '-s', '--no-show-signature',
                                    '--no-decorate', '--no-abbrev-commit',
                                    '--format=format:%P', commit])


def git_show_parent_time(commit):
    return subprocess.check_output([GIT, 'show', '-s', '--no-show-signature',
                                    '--no-decorate', '--no-abbrev-commit',
                                    '--format=format:%ct', commit])



def git_show_tree_hash(commit):
    return subprocess.check_output([GIT, 'show', '-s', '--no-show-signature',
                                    '--no-decorate', '--no-abbrev-commit',
                                    '--format=format:%T', commit])


def git_show_commit_hash(commit):
    return subprocess.check_output([GIT, 'show', '-s', '--no-show-signature',
                                    '--no-decorate', '--no-abbrev-commit',
                                    '--format=%H', commit])


def git_show_commit_subject(commit):
    return subprocess.check_output([GIT, 'show', '-s', '--no-show-signature',
                                    '--no-decorate', '--no-abbrev-commit',
                                    commit])

def git_checkout(branch):
    return subprocess.call([GIT, 'checkout', '--force', '--quiet', branch])


def git_verify_commit(datadir, commit):
    """Verify the {commit} using the gpg.sh file from our {datadir}, which checks
    the {commit} signature against the trusted keys present in this same
    {datadir}"""
    return subprocess.call([GIT, '-c', 'gpg.program={}/gpg.sh'.format(datadir),
                            'verify-commit', commit], stdout=subprocess.DEVNULL)


def tree_sha512sum(commit='HEAD'):
    overall = hashlib.sha512()

    # request metadata for entire tree, recursively
    files = []
    blob_by_name = {}
    for line in subprocess.check_output([GIT, 'ls-tree', '--full-tree', '-r', commit]).splitlines():
        name_sep = line.index(b'\t')
        # perms, 'blob' or 'commit', blobid
        metadata = line[:name_sep].split()
        # Path to file
        name = line[name_sep+1:]
        # If we hit a submodule, get the SHA512 of its tree as well.
        if metadata[1] == b'commit':
            curdir = os.path.abspath(os.getcwd())
            os.chdir(name)
            overall.update(bytes.fromhex(tree_sha512sum(metadata[2].decode())))
            os.chdir(curdir)
            continue
        assert metadata[1] == b'blob', f"{metadata}"
        files.append(name)
        blob_by_name[name] = metadata[2]

    files.sort()
    # open connection to git-cat-file in batch mode to request data for all blobs
    # this is much faster than launching it per file
    p = subprocess.Popen([GIT, 'cat-file', '--batch'], stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    for f in files:
        blob = blob_by_name[f]
        # request blob
        p.stdin.write(blob + b'\n')
        p.stdin.flush()
        # read header: blob, "blob", size
        reply = p.stdout.readline().split()
        assert(reply[0] == blob and reply[1] == b'blob')
        size = int(reply[2])
        # hash the blob data
        intern = hashlib.sha512()
        ptr = 0
        while ptr < size:
            bs = min(65536, size - ptr)
            piece = p.stdout.read(bs)
            if len(piece) == bs:
                intern.update(piece)
            else:
                raise IOError('Premature EOF reading git cat-file output')
            ptr += bs
        dig = intern.hexdigest()
        assert(p.stdout.read(1) == b'\n') # ignore LF that follows blob data
        # update overall hash with file hash
        overall.update(dig.encode("utf-8"))
        overall.update("  ".encode("utf-8"))
        overall.update(f)
        overall.update("\n".encode("utf-8"))
    p.stdin.close()
    if p.wait():
        raise IOError('Non-zero return value executing git cat-file')
    return overall.hexdigest()


def main():
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--disable-tree-check', action='store_false',
                        dest='verify_tree', help='disable SHA-512 tree check')
    parser.add_argument('--clean-merge', type=float, dest='clean_merge',
                        default=float('inf'), help='Only check clean merge '
                        'after <NUMBER> days ago (default: %(default)s)',
                        metavar='NUMBER')
    parser.add_argument("repository", help="The repository to verify the"
                        " commits for. Used to determine data files.")
    parser.add_argument('commit', nargs='?', default='HEAD', help='Check clean merge up to commit <commit>')
    args = parser.parse_args()

    # Check the directories
    bindir = os.path.dirname(os.path.abspath(__file__))
    datadir = os.path.join(bindir, args.repository)
    if not os.path.exists(datadir):
        print(f"{datadir} does not exist", file=sys.stderr)
        sys.exit(1)
    if os.path.split(os.getcwd())[-1] != args.repository:
        print(f"Verifying for {args.repository} but you are in {os.getcwd()}",
              file=sys.stderr)
        sys.exit(1)

    # Read the data files (root of trust, commits to bypass, ..)
    print("Using verify-commits data from " + datadir)
    trusted_root_path = os.path.join(datadir, "trusted-git-root")
    verified_root = open(trusted_root_path, "r", encoding="utf8").read().splitlines()[0]
    sha_path = os.path.join(datadir, "trusted-sha512-root-commit")
    verified_sha512_root = open(sha_path, "r", encoding="utf8").read().splitlines()[0]
    revsig_path = os.path.join(datadir, "allow-revsig-commits")
    revsig_allowed = open(revsig_path, "r", encoding="utf-8").read().splitlines()
    unclean_path = os.path.join(datadir, "allow-unclean-merge-commits")
    unclean_merge_allowed = open(unclean_path, "r", encoding="utf-8").read().splitlines()
    incorrect_sha_path = os.path.join(datadir, "allow-incorrect-sha512-commits")
    incorrect_sha512_allowed = open(incorrect_sha_path, "r", encoding="utf-8").read().splitlines()
    trusted_keys_path = os.path.join(datadir, "trusted-keys")

    # Set commit and branch and set variables
    current_commit = args.commit
    if ' ' in current_commit:
        print("Commit must not contain spaces", file=sys.stderr)
        sys.exit(1)
    verify_tree = args.verify_tree
    no_sha1 = True
    prev_commit = ""
    initial_commit = current_commit
    branch = git_show_commit_hash(initial_commit).decode('utf8').splitlines()[0]

    # Iterate through commits
    while True:
        if current_commit == verified_root:
            print('There is a valid path from "{}" to {} where all commits are signed!'.format(initial_commit, verified_root))
            sys.exit(0)
        if current_commit == verified_sha512_root:
            if verify_tree:
                print("All Tree-SHA512s matched up to {}".format(verified_sha512_root), file=sys.stderr)
            verify_tree = False
            no_sha1 = False

        os.environ["REVAULT_VERIFY_COMMITS_ALLOW_SHA1"] = "0" if no_sha1 else "1"
        os.environ["REVAULT_VERIFY_COMMITS_ALLOW_REVSIG"] = "1" if current_commit in revsig_allowed else "0"
        os.environ["REVAULT_VERIFY_COMMITS_TRUSTED_KEYS_PATH"] = trusted_keys_path

        # Check that the commit (and parents) was signed with a trusted key
        if git_verify_commit(bindir, current_commit):
            if prev_commit != "":
                print("No parent of {} was signed with a trusted key!".format(prev_commit), file=sys.stderr)
                print("Parents are:", file=sys.stderr)
                parents = git_show_parents_hashes(prev_commit).decode('utf8').splitlines()[0].split(' ')
                for parent in parents:
                    git_show_commit_hash(parent)
            else:
                print("{} was not signed with a trusted key!".format(current_commit), file=sys.stderr)
            sys.exit(1)

        # Check the Tree-SHA512
        if (verify_tree or prev_commit == "") and current_commit not in incorrect_sha512_allowed:
            tree_hash = tree_sha512sum(current_commit)
            if ("Tree-SHA512: {}".format(tree_hash)) not in subprocess.check_output([GIT, 'show', '-s', '--format=format:%B', current_commit]).decode('utf8').splitlines():
                print("Tree-SHA512 did not match for commit " + current_commit, file=sys.stderr)
                sys.exit(1)

        # Merge commits should only have two parents
        parents = git_show_parents_hashes(current_commit).decode('utf8').splitlines()[0].split(' ')
        if len(parents) > 2:
            print("Commit {} is an octopus merge".format(current_commit), file=sys.stderr)
            sys.exit(1)

        # Check that the merge commit is clean
        commit_time = int(git_show_parent_time(current_commit).decode('utf8').splitlines()[0])
        check_merge = commit_time > time.time() - args.clean_merge * 24 * 60 * 60  # Only check commits in clean_merge days
        allow_unclean = current_commit in unclean_merge_allowed
        if len(parents) == 2 and check_merge and not allow_unclean:
            current_tree = git_show_tree_hash(current_commit).decode('utf8').splitlines()[0]
            git_checkout(parents[0])
            subprocess.call([GIT, 'merge', '--no-ff', '--quiet', '--no-gpg-sign', parents[1]], stdout=subprocess.DEVNULL)
            recreated_tree = git_show_tree_hash("HEAD").decode('utf8').splitlines()[0]
            if current_tree != recreated_tree:
                print("Merge commit {} is not clean".format(current_commit), file=sys.stderr)
                subprocess.call([GIT, 'diff', current_commit])
                git_checkout(branch)
                sys.exit(1)
            git_checkout(branch)

        prev_commit = current_commit
        current_commit = parents[0]

if __name__ == '__main__':
    main()
