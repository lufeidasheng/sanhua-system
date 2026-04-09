import pygame
import random
import math

pygame.init()
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()

# 定义筋斗云轮廓多边形（近似三朵云连在一起的形状）
# 这些点需要你根据筋斗云形状手动调整
cloud_polygon = [
    (300, 300), (340, 280), (380, 290), (410, 320), (430, 360),
    (420, 400), (380, 430), (340, 420), (310, 390), (280, 360),

    (350, 280), (390, 250), (420, 260), (450, 280), (480, 320),
    (460, 350), (440, 380), (400, 410), (360, 390), (330, 350),

    (400, 270), (440, 240), (480, 260), (520, 300), (510, 340),
    (470, 370), (430, 400), (390, 380), (370, 350),
]

def point_in_polygon(x, y, poly):
    # 射线法判断点是否在多边形内部
    num = len(poly)
    j = num - 1
    c = False
    for i in range(num):
        if ((poly[i][1] > y) != (poly[j][1] > y)) and \
                (x < (poly[j][0] - poly[i][0]) * (y - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0]):
            c = not c
        j = i
    return c

class Particle:
    def __init__(self, pos):
        self.base_pos = pos
        self.pos = list(pos)
        self.size = random.randint(4, 7)
        self.life = 100
        self.color = (255, 215, 0)
        self.breath_phase = random.uniform(0, math.pi * 2)

    def update(self, time_sec):
        self.life -= 1
        # 呼吸缩放透明度和大小
        breath = 0.3 * math.sin(time_sec * 3 + self.breath_phase)
        self.size = 5 + breath * 2
        alpha = int(200 + breath * 55)
        self.color_with_alpha = (*self.color, max(0, min(255, alpha)))
        # 轻微随机抖动
        self.pos[0] = self.base_pos[0] + random.uniform(-1, 1)
        self.pos[1] = self.base_pos[1] + random.uniform(-1, 1)

    def draw(self, surface):
        s = pygame.Surface((int(self.size*2), int(self.size*2)), pygame.SRCALPHA)
        pygame.draw.circle(s, self.color_with_alpha, (int(self.size), int(self.size)), int(self.size))
        surface.blit(s, (self.pos[0] - self.size, self.pos[1] - self.size))

# 在多边形内均匀撒粒子
def generate_particles_in_polygon(poly, count):
    min_x = min(p[0] for p in poly)
    max_x = max(p[0] for p in poly)
    min_y = min(p[1] for p in poly)
    max_y = max(p[1] for p in poly)
    particles = []
    tries = 0
    while len(particles) < count and tries < count * 10:
        x = random.uniform(min_x, max_x)
        y = random.uniform(min_y, max_y)
        if point_in_polygon(x, y, poly):
            particles.append(Particle((x, y)))
        tries += 1
    return particles

particles = generate_particles_in_polygon(cloud_polygon, 200)

running = True
while running:
    dt = clock.tick(60) / 1000
    time_sec = pygame.time.get_ticks() / 1000

    screen.fill((10, 10, 30))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    for p in particles:
        p.update(time_sec)
        p.draw(screen)

    # 画轮廓线（辅助观察）
    pygame.draw.polygon(screen, (255, 200, 50), cloud_polygon, 2)

    pygame.display.flip()

pygame.quit()
