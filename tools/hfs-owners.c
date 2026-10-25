/* Offline ownership repair for a locally authored, unmounted HFS+ image.
 * Uses libdmg-hfsplus; names are traversed as catalog records, not lossy ASCII. */
#include <hfs/hfsplus.h>
#include <hfs/hfslib.h>
#include <string.h>

char endianness;
static unsigned long records;
static int name_is(const HFSUniStr255 *name, const char *ascii)
{
    size_t n = strlen(ascii);
    if (name->length != n) return 0;
    for (size_t i = 0; i < n; ++i) if (name->unicode[i] != (unsigned char)ascii[i]) return 0;
    return 1;
}
static void walk(Volume *volume, HFSCatalogNodeID folder, unsigned state)
{
    CatalogRecordList *list = getFolderContents(folder, volume);
    for (CatalogRecordList *item = list; item; item = item->next) {
        unsigned next = state;
        if (state == 0 && name_is(&item->name, "private")) next = 1;
        else if (state == 1 && name_is(&item->name, "var")) next = 2;
        else if (state == 2 && name_is(&item->name, "mobile")) next = 3;
        uint32_t uid = next == 3 ? 501 : 0;
        if (item->record->recordType == kHFSPlusFolderRecord) {
            HFSPlusCatalogFolder *record = (HFSPlusCatalogFolder *)item->record;
            record->permissions.ownerID = uid;
            record->permissions.groupID = uid;
            updateCatalog(volume, item->record);
            walk(volume, record->folderID, next);
        } else if (item->record->recordType == kHFSPlusFileRecord) {
            HFSPlusCatalogFile *record = (HFSPlusCatalogFile *)item->record;
            record->permissions.ownerID = uid;
            record->permissions.groupID = uid;
            updateCatalog(volume, item->record);
        }
        ++records;
    }
    releaseCatalogRecordList(list);
}
int main(int argc, char **argv)
{
    uint16_t endian_probe = 1;
    endianness = *(uint8_t *)&endian_probe ? IS_LITTLE_ENDIAN : IS_BIG_ENDIAN;
    if (argc != 3) { fprintf(stderr, "usage: hfs-owners IMAGE OWNERS.tsv\n"); return 2; }
    io_func *io = openFlatFile(argv[1]);
    if (!io) return 3;
    Volume *volume = openVolume(io);
    if (!volume) { CLOSE(io); return 4; }
    walk(volume, kHFSRootFolderID, 0);
    if (!chownFile("/", 0, 0, volume)) return 5;
    FILE *overrides = fopen(argv[2], "r");
    if (!overrides) return 6;
    char *line = NULL; size_t capacity = 0;
    while (getline(&line, &capacity, overrides) > 0) {
        unsigned uid, gid; int start = 0;
        if (sscanf(line, "%u\t%u\t%n", &uid, &gid, &start) != 2) return 7;
        char *path = line + start;
        path[strcspn(path, "\n")] = 0;
        if (!chownFile(path, uid, gid, volume)) {
            fprintf(stderr, "Missing ownership target: %s\n", path); return 8;
        }
    }
    free(line); fclose(overrides);
    closeVolume(volume); CLOSE(io);
    printf("Repaired %lu catalog records and applied ownership overrides\n", records);
    return 0;
}
