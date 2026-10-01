import base64, subprocess
p = subprocess.run(["git","credential","fill"], cwd=r"C:\youtube_pipeline",
                   input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True)
tok = next((l.split("=",1)[1].strip() for l in p.stdout.splitlines() if l.startswith("password=")), None)
b64 = base64.b64encode(("x-access-token:" + tok).encode()).decode()
r = subprocess.run(["git","-c","credential.helper=",
                    "-c","http.https://github.com/.extraheader=AUTHORIZATION: basic " + b64,
                    "push","origin","main"], cwd=r"C:\youtube_pipeline", capture_output=True, text=True, timeout=120)
print("rc=", r.returncode); print(r.stdout[-300:]); print(r.stderr[-400:])
