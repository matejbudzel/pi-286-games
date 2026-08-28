import unittest


def pillarbox_geometry(physical_width, physical_height, logical_width, logical_height, bpp=16):
    if bpp != 16 or physical_height != logical_height or logical_width > physical_width:
        return None
    return (physical_width - logical_width) // 2


def copy_dirty(physical, physical_width, physical_height, stride_pixels, logical, logical_width, logical_height, rect):
    offset = pillarbox_geometry(physical_width, physical_height, logical_width, logical_height)
    if offset is None:
        return False
    x, y, width, height = rect
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(logical_width, x + width), min(logical_height, y + height)
    for row in range(y1, y2):
        destination = row * stride_pixels + offset + x1
        source = row * logical_width + x1
        physical[destination:destination + x2 - x1] = logical[source:source + x2 - x1]
    return True


class PillarboxCopyMathTests(unittest.TestCase):
    def test_854x480_centers_640x480_at_107_pixels(self):
        self.assertEqual(pillarbox_geometry(854, 480, 640, 480), 107)

    def test_dirty_rectangle_is_clipped_and_translated(self):
        physical = [0] * (854 * 480)
        logical = [0] * (640 * 480)
        logical[0] = 11
        logical[1 * 640 + 1] = 22
        copy_dirty(physical, 854, 480, 854, logical, 640, 480, (-1, -1, 3, 3))
        self.assertEqual(physical[107], 11)
        self.assertEqual(physical[854 + 108], 22)

    def test_pillars_remain_black(self):
        physical = [0] * (854 * 480)
        logical = [9] * (640 * 480)
        copy_dirty(physical, 854, 480, 854, logical, 640, 480, (0, 0, 640, 480))
        self.assertEqual(physical[106], 0)
        self.assertEqual(physical[747], 0)
        self.assertEqual(physical[107], 9)
        self.assertEqual(physical[746], 9)

    def test_identical_geometry_has_zero_offset(self):
        self.assertEqual(pillarbox_geometry(640, 480, 640, 480), 0)

    def test_invalid_geometry_is_safe(self):
        self.assertIsNone(pillarbox_geometry(640, 480, 641, 480))
        self.assertIsNone(pillarbox_geometry(854, 481, 640, 480))
        self.assertIsNone(pillarbox_geometry(854, 480, 640, 480, 32))
