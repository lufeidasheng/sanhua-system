import pygame
import sys
import random
import math

# 初始化 Pygame
pygame.init()

# 设置窗口
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("金黄云朵粒子动画")

# 粒子数量
PARTICLE_COUNT = 300

# 云朵中心位置
cloud_center = [WIDTH // 2, HEIGHT // 2]

# 云朵形状控制参数
cloud_shape = {
    "radius_x": WIDTH // 4,
    "radius_y": HEIGHT // 6,
    "lumps": 5,
    "lump_size": 0.3
}

# 粒子类
class Particle:
    def __init__(self):
        self.reset()
        # 初始位置随机分布在云朵形状内
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(0, cloud_shape["radius_x"] * 0.7)
        self.x = cloud_center[0] + math.cos(angle) * distance
        self.y = cloud_center[1] + math.sin(angle) * distance * (cloud_shape["radius_y"] / cloud_shape["radius_x"])
        
        # 存储原始位置（云朵形状）
        self.origin_x = self.x
        self.origin_y = self.y
    
    def reset(self):
        # 随机大小
        self.size = random.uniform(2, 7)
        
        # 随机速度（缓慢）
        self.vx = random.uniform(-0.1, 0.1)
        self.vy = random.uniform(-0.1, 0.1)
        
        # 随机颜色（金黄渐变）
        gold_variation = random.uniform(0, 0.3)
        self.color = (
            255,  # R
            int(200 + random.uniform(0, 55)),  # G
            int(random.uniform(0, 50)),  # B
        )
        
        # 移动范围限制
        self.max_distance = random.uniform(10, 30)
    
    def update(self):
        # 更新位置
        self.x += self.vx
        self.y += self.vy
        
        # 计算与原始位置的距离
        dx = self.x - self.origin_x
        dy = self.y - self.origin_y
        distance = math.sqrt(dx**2 + dy**2)
        
        # 如果移动太远，则返回原始位置
        if distance > self.max_distance:
            self.vx = -self.vx * 0.5
            self.vy = -self.vy * 0.5
        
        # 随机扰动
        if random.random() < 0.02:
            self.vx += random.uniform(-0.1, 0.1)
            self.vy += random.uniform(-0.1, 0.1)
        
        # 限制速度
        speed = math.sqrt(self.vx**2 + self.vy**2)
        max_speed = 0.5
        if speed > max_speed:
            self.vx = (self.vx / speed) * max_speed
            self.vy = (self.vy / speed) * max_speed
    
    def draw(self, surface):
        # 绘制粒子（带发光效果）
        glow_surf = pygame.Surface((self.size * 4, self.size * 4), pygame.SRCALPHA)
        pygame.draw.circle(
            glow_surf,
            (*self.color, 50),  # 更透明的外发光
            (self.size * 2, self.size * 2),
            self.size * 2
        )
        surface.blit(glow_surf, (self.x - self.size * 2, self.y - self.size * 2))
        
        # 绘制粒子核心
        pygame.draw.circle(
            surface,
            self.color,
            (int(self.x), int(self.y)),
            int(self.size)
        )

# 初始化粒子
particles = [Particle() for _ in range(PARTICLE_COUNT)]

# 背景渐变（从深蓝到金黄）
def draw_background(surface):
    for y in range(HEIGHT):
        # 计算渐变颜色
        ratio = y / HEIGHT
        r = int(26 * (1 - ratio) + 255 * ratio)
        g = int(42 * (1 - ratio) + 215 * ratio)
        b = int(108 * (1 - ratio))
        pygame.draw.line(surface, (r, g, b), (0, y), (WIDTH, y))

# 主循环
clock = pygame.time.Clock()
running = True

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
    
    # 绘制背景
    draw_background(screen)
    
    # 更新和绘制粒子
    for particle in particles:
        particle.update()
        particle.draw(screen)
    
    pygame.display.flip()
    clock.tick(60)  # 60 FPS

pygame.quit()
sys.exit()
