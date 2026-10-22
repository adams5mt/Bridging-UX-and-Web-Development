# Death House PC miniatures

3D miniatures of the ten pregenerated characters from the Death House Pregens page, made with the Meshy API.

Every figure stands on the same base: a 25 mm round, 3.5 mm tall, with a bevelled edge. Figures are scaled sole-to-crown, so they match each other on the table.

| Character | Class | Height |
|---|---|---|
| Mathias Kell | Human Fighter | 30 mm |
| Isolde Marrec | Human Paladin | 30 mm |
| Agna Brightvein | Dwarf Cleric | 22 mm |
| Varis | Wood Elf Druid | 30 mm |
| Ambrose Tinwick | Rock Gnome Wizard | 18 mm |
| Sorrow | Tiefling Warlock | 30 mm |
| Fennick Crowe | Halfling Rogue | 18 mm |
| Luca Moravek | Human Bard | 30 mm |
| Elowen Ashgrave | High Elf Ranger | 30 mm |
| Volen Graymane | Orc Barbarian | 32 mm |

## Files

In `out/<id>/`:

- `<id>.stl`: the figure and base as one mesh, Z-up, in millimetres, ready for a slicer.
- `<id>.glb`: a textured, painted version on a dark base, for viewers, VTTs and AR.
- `concept.png`: the concept art the model was built from.
- `thumb-*.png`: Meshy's front, back, left and right renders.
- `based.png`: a front and side check of the figure on its base.

The `out/models.png`, `out/based.png` and `out/concepts.png` sheets show all ten side by side.

## How they were made

`characters.json` holds a shared style prompt, the base size, and a look and height for each character. The looks are drawn from each character's class, species, background, gear and relic.

`generate.py` runs three steps for each character:

1. **concept**: Meshy text-to-image (nano-banana-2, 6 credits).
2. **model**: Meshy image-to-3D from that image (meshy-7.1, PBR textures, about 100k triangles, 30 credits).
3. **base**: local and free. It scales the figure, finds its feet, centres them on the base and exports the STL and GLB.

```sh
pip install trimesh numpy scipy shapely pillow
export MESHY_API_KEY=...
python3 generate.py concept volen   # redo one step for one character
python3 generate.py all             # every step for everyone
```

Meshy task IDs are saved in `state.json`, so a re-run reuses finished work instead of paying for it again. To regenerate a character, edit its `look`, delete its entry in `state.json` and run `all` for that id. Raw Meshy downloads (`raw.glb`) aren't committed.

## Printing notes

Thin parts are fragile at this scale: Elowen's bowstring, Varis's staff, Sorrow's tail and Isolde's feather. Resin printers handle them best. Volen's greataxe sticks about 1 mm past the edge of the base.
