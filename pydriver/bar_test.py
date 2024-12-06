from driver import *
import time

bar_mmap_file = '/dev/bdma_user_mmap0'
bar = BlueRdmaBarInterface(bar_mmap_file)

def test_read(addr):
    assert (addr % 4 == 0)
    value = bar.read_csr_blocking(addr)
    print("Bar %x : %x" % (addr, value))

test_read(4096)
# test_read(111)

time.sleep(0.2)

# bar.write_csr_blocking(0, 0xaaa)

# bar.write_csr_blocking(111, 0xbbb)

# time.sleep(0.2)

# test_read(0)
# test_read(111)