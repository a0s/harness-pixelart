# swordsman -- art direction brief

## Subject
Blond swordsman, three-quarter front view, standing at rest with his sword
planted point-down on the ground beside him.

## Read at 1x
The planted sword and the blond head. If those two read at 32 px, the sprite works.

## Canvas & palette
- canvas: 32x32, feet on the ground line at y=31
- palette: sweetie-16, locked
- colour budget: 12 of the 16

## Light
- direction: upper-left
- the left pauldron, the hair crown and the left side of the blade take the key;
  the right side of every form falls to the shadow value and reaches the outline

## Style rules
- outline: full dark keyline in `#1a1c2c`, the palette's darkest
- dither: none at this size
- hue shift: shadows toward violet, highlights toward warm
- detail: three materials only -- cloth, leather, steel

## Animation
- 4-frame ping-pong idle, 260/180/260/180 ms
- moving: chest (breath), hips (weight shift), the unweighted heel
- holding: the sword, both feet, the head silhouette
- anchor: bottom -- the ground contact never moves

## Out of scope
Facial expression beyond two eye pixels, cape, background, walk cycle.
