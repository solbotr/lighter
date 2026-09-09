import _vps_deploy as d

c = d.connect()
d.run(c, "cmd /c tasklist | findstr /I python")
d.run(c, d.tail_log_cmd(50))
c.close()
