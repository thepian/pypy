from sup import run

def w(N, start):
    def f5(a, b, c, d, e):
        pass
    def f6(a, b, c, d, e, f):
        pass

    start()

    i = 0
    while i < N:
        f5(1, 2, 3, 4, 5)
        f5(1, 2, 3, 4, 5)
        f5(1, 2, 3, 4, 5)
        f5(1, 2, 3, 4, 5)
        f5(1, 2, 3, 4, 5)
        f5(1, 2, 3, 4, 5)

        f6(1, 2, 3, 4, 5, 6)
        f6(1, 2, 3, 4, 5, 6)
        f6(1, 2, 3, 4, 5, 6)
        f6(1, 2, 3, 4, 5, 6)
        f6(1, 2, 3, 4, 5, 6)
        f6(1, 2, 3, 4, 5, 6)            
        i+=1

run(w, 1000)
