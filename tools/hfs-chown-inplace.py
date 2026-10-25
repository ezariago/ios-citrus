#!/usr/bin/env python3
"""Repair HFS+ catalog ownership in place, without touching B-tree structure.

Unlike tools/hfs-owners.c (libdmg-hfsplus updateCatalog), this never searches,
inserts or extends the B-tree: it parses the catalog records itself and rewrites
only the 8 bytes of ownerID/groupID inside existing leaf records. That makes it
safe for large volumes whose catalog is full, and it does not depend on a
particular key comparison rule.

Rules:
  * everything defaults to root:wheel (0:0)
  * the /private/var/mobile subtree becomes mobile:mobile (501:501)
  * extra "uid<TAB>gid<TAB>/path" overrides are applied last

The image must be unmounted. Changed nodes are checkpointed to a rollback file.
"""

import argparse
import struct
import sys

BS = 4096
VOLUME_HEADER_OFFSET = 1024
CATALOG_FILE_ID = 4
ATTRIBUTES_FILE_ID = 8
ROOT_FOLDER_CNID = 2
FOLDER_RECORD, FILE_RECORD = 1, 2
LEAF_NODE = 0xFF
FOLDER = "folder"
FILE = "file"


class HFS:
    def __init__(self, path):
        self.f = open(path, "r+b")
        self.f.seek(VOLUME_HEADER_OFFSET)
        vh = self.f.read(512)
        if vh[0:2] not in (b"H+", b"HX"):
            raise SystemExit("not an HFS+ volume header: %r" % vh[0:2])
        self.block_size = struct.unpack(">I", vh[40:44])[0]
        if self.block_size != BS:
            raise SystemExit("unexpected block size %d" % self.block_size)
        self.total_blocks = struct.unpack(">I", vh[44:48])[0]
        self.file_count = struct.unpack(">I", vh[32:36])[0]
        self.folder_count = struct.unpack(">I", vh[36:40])[0]
        self.catalog = self._fork(vh, 272)
        self.extents = self._fork(vh, 192)
        self.overflow = self._overflow_extents()
        self.segments = self._segments()

    def _fork(self, vh, offset):
        logical, clump, blocks = struct.unpack(">QII", vh[offset:offset + 16])
        extents = [struct.unpack(">II", vh[offset + 16 + i * 8:offset + 24 + i * 8])
                   for i in range(8)]
        return {"logical": logical, "blocks": blocks,
                "extents": [(s, c) for s, c in extents if c]}

    def read(self, offset, length):
        self.f.seek(offset)
        return self.f.read(length)

    def write(self, offset, data):
        self.f.seek(offset)
        self.f.write(data)

    def _btree_header(self, extents):
        node0 = self._read_extents(extents, 0, 512)
        rec = node0[14:]
        depth, root, leaf_records, first_leaf, last_leaf = struct.unpack(">HIIII", rec[0:18])
        node_size, max_key = struct.unpack(">HH", rec[18:22])
        total_nodes, free_nodes = struct.unpack(">II", rec[22:30])
        return {"depth": depth, "root": root, "leafRecords": leaf_records,
                "firstLeaf": first_leaf, "lastLeaf": last_leaf,
                "nodeSize": node_size, "totalNodes": total_nodes,
                "freeNodes": free_nodes}

    def _extents_of(self, extents):
        """Yield (logical_start, physical_start, block_count) for a fork."""
        logical = 0
        for start, count in extents:
            yield logical, start, count
            logical += count

    def _read_extents(self, extents, offset, length):
        out = b""
        while len(out) < length:
            rel = offset + len(out)
            for logical, physical, count in self._extents_of(extents):
                span = count * BS
                if logical * BS <= rel < (logical + count) * BS:
                    take = min(length - len(out), (logical + count) * BS - rel)
                    out += self.read(physical * BS + (rel - logical * BS), take)
                    break
            else:
                raise SystemExit("unmapped catalog offset %d" % rel)
        return out

    def _overflow_extents(self):
        extents = self.extents["extents"]
        header = self._btree_header(extents)
        found = []
        node = header["firstLeaf"]
        nodes = 0
        while node:
            raw = self._read_extents(extents, node * BS, BS)
            f_link, b_link, kind, height, count = struct.unpack(">IIBBH", raw[0:12])
            offsets = [struct.unpack(">H", raw[BS - 2 * (i + 1):BS - 2 * i])[0]
                       for i in range(count + 1)]
            for i in range(count):
                record = raw[offsets[i]:offsets[i + 1]]
                key_length = struct.unpack(">H", record[0:2])[0]
                key = record[2:2 + key_length]
                fork_type, pad, file_id, start_block = struct.unpack(">BBII", key)
                body = record[2 + key_length:]
                pairs = [struct.unpack(">II", body[j * 8:j * 8 + 8]) for j in range(8)]
                if fork_type == 0 and file_id == CATALOG_FILE_ID:
                    found.append((start_block, [(s, c) for s, c in pairs if c]))
            node = f_link
            nodes += 1
            if nodes > header["totalNodes"]:
                raise SystemExit("extents overflow chain does not terminate")
        found.sort()
        result = []
        for _, pairs in found:
            result.extend(pairs)
        return result

    def _segments(self):
        extents = self.catalog["extents"] + self.overflow
        segments = []
        logical = 0
        for start, count in extents:
            segments.append((logical, start, count))
            logical += count
        expected = self.catalog["blocks"]
        if logical != expected:
            raise SystemExit("catalog extents cover %d blocks, header says %d"
                             % (logical, expected))
        if self.catalog["logical"] != expected * self.block_size:
            raise SystemExit("catalog fork logical size disagrees with block count")
        return segments

    def node_offset(self, node):
        block = node
        for logical, physical, count in self.segments:
            if logical <= block < logical + count:
                return (physical + (block - logical)) * BS
        raise SystemExit("node %d is not mapped by any catalog extent" % node)

    def catalog_header(self):
        return self._btree_header(self.catalog["extents"])


def read_records(hfs):
    header = hfs.catalog_header()
    if header["nodeSize"] != BS:
        raise SystemExit("unexpected catalog node size %d" % header["nodeSize"])
    items = {}
    nodes = 0
    for node in range(header["totalNodes"]):
        offset = hfs.node_offset(node)
        raw = hfs.read(offset, BS)
        f_link, b_link, kind, height, count = struct.unpack(">IIBBH", raw[0:12])
        if kind != LEAF_NODE or height != 1:
            continue
        nodes += 1
        offsets = [struct.unpack(">H", raw[BS - 2 * (i + 1):BS - 2 * i])[0]
                   for i in range(count + 1)]
        for i in range(count):
            record = raw[offsets[i]:offsets[i + 1]]
            key_length = struct.unpack(">H", record[0:2])[0]
            parent = struct.unpack(">I", record[2:6])[0]
            name_length = struct.unpack(">H", record[6:8])[0]
            name = record[8:8 + 2 * name_length].decode("utf-16-be", "surrogatepass")
            data = 2 + key_length
            record_type = struct.unpack(">H", record[data:data + 2])[0]
            if record_type not in (FOLDER_RECORD, FILE_RECORD):
                continue
            cnid = struct.unpack(">I", record[data + 8:data + 12])[0]
            owner, group = struct.unpack(">II", record[data + 32:data + 40])
            items[cnid] = {
                "parent": parent, "name": name, "node": node,
                "owner_at": offset + offsets[i] + data + 32,
                "kind": FOLDER if record_type == FOLDER_RECORD else FILE,
                "uid": owner, "gid": group,
            }
    return items, nodes


def child(items, parent, name):
    for cnid, item in items.items():
        if item["parent"] == parent and item["name"] == name:
            return cnid
    return None


def resolve(items, path):
    cnid = ROOT_FOLDER_CNID
    for part in [p for p in path.split("/") if p]:
        cnid = child(items, cnid, part)
        if cnid is None:
            return None
    return cnid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("owners", nargs="?", help="uid<TAB>gid<TAB>/path overrides")
    parser.add_argument("--rollback", default=None, help="write changed nodes here")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-overrides", action="store_true",
                        help="preserve all other ownership; only apply paths in the TSV")
    args = parser.parse_args()
    if args.only_overrides and not args.owners:
        parser.error("--only-overrides requires an owners TSV")

    hfs = HFS(args.image)
    header = hfs.catalog_header()
    items, leaves = read_records(hfs)
    expected = hfs.file_count + hfs.folder_count
    print("catalog: %d nodes, %d leaves, %d items (volume header: %d files + %d folders = %d)"
          % (header["totalNodes"], leaves, len(items),
             hfs.file_count, hfs.folder_count, expected))
    if len(items) != expected:
        raise SystemExit("catalog item count %d does not match volume header %d"
                         % (len(items), expected))

    mobile = resolve(items, "/private/var/mobile")
    if mobile is None:
        raise SystemExit("cannot resolve /private/var/mobile")
    print("mobile cnid", mobile)

    parents = {}
    for cnid, item in items.items():
        parents[cnid] = item["parent"]

    def in_mobile(cnid):
        seen = 0
        while cnid and cnid != ROOT_FOLDER_CNID:
            if cnid == mobile:
                return True
            cnid = parents.get(cnid)
            seen += 1
            if seen > 4096:
                break
        return cnid == mobile

    wanted = {}
    if not args.only_overrides:
        for cnid in items:
            wanted[cnid] = (501, 501) if in_mobile(cnid) else (0, 0)

    if args.owners:
        with open(args.owners) as handle:
            for line in handle:
                line = line.rstrip("\n")
                if not line:
                    continue
                fields = line.split("\t")
                if len(fields) != 3:
                    raise SystemExit("bad override line: %r" % line)
                uid, gid, path = int(fields[0]), int(fields[1]), fields[2]
                cnid = resolve(items, path)
                if cnid is None:
                    raise SystemExit("override target not found: %s" % path)
                wanted[cnid] = (uid, gid)

    changes = {}
    for cnid, (uid, gid) in wanted.items():
        item = items[cnid]
        if (item["uid"], item["gid"]) != (uid, gid):
            changes[cnid] = (uid, gid)

    print("items needing change: %d of %d" % (len(changes), len(items)))
    if args.dry_run:
        return 0

    by_node = {}
    for cnid, (uid, gid) in changes.items():
        item = items[cnid]
        by_node.setdefault(item["node"], []).append((item["owner_at"], uid, gid))

    rollback = open(args.rollback, "wb") if args.rollback else None
    for node, edits in sorted(by_node.items()):
        offset = hfs.node_offset(node)
        raw = bytearray(hfs.read(offset, BS))
        if rollback:
            rollback.write(struct.pack(">Q", offset))
            rollback.write(bytes(raw))
        for at, uid, gid in edits:
            struct.pack_into(">II", raw, at - offset, uid, gid)
        hfs.write(offset, bytes(raw))
    if rollback:
        rollback.write(struct.pack(">Q", 0))
        rollback.close()
    hfs.f.flush()
    print("rewrote %d catalog nodes" % len(by_node))
    return 0


if __name__ == "__main__":
    sys.exit(main())
