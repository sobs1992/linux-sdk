"""The 3D GameStudio A6 engine's check of a game's main .WRS (maindata.dae
0x4227c0): the sum of the first 16 KB and the file size make 5 decimal
digits, compared with a number built into the engine (Daemonica: 72936)."""


def wrs_check(data, n=None):
    """the check number of data; with n, of data's first 16 KB in a file of n bytes"""
    s = sum(data[:0x4000])
    if n is None:
        n = len(data)
    d = [(((s >> 12) & 7) ^ (n & 0x1f)) % 10,
         (((s >> 9) & 7) ^ ((n >> 5) & 0x1f)) % 10,
         (((s >> 6) & 7) ^ ((n >> 10) & 0x1f)) % 10,
         (((s >> 3) & 7) ^ ((n >> 15) & 0x1f)) % 10,
         ((s & 7) ^ ((n >> 20) & 0x1f)) % 10]
    return int(''.join(map(str, d)))


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        print(p, wrs_check(open(p, 'rb').read()))
