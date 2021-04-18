import traceback
from typing import Tuple

from .Exceptions import *
from .helpers import *
from .Config import RunConfig
from .Registers import Registers
from .Syscall import SyscallInterface, Syscall
from .debug import launch_debug_session

import typing

if typing.TYPE_CHECKING:
    from . import MMU, Executable, LoadedExecutable, LoadedInstruction


class CPU:
    def __init__(self, conf: RunConfig):
        from . import MMU
        self.pc = 0
        self.cycle = 0
        self.exit = False
        self.exit_code = 0
        self.conf = conf

        self.mmu = MMU(conf)
        self.regs = Registers(conf)
        self.syscall_int = SyscallInterface()

        # provide global syscall symbols if option is set
        if conf.include_scall_symbols:
            self.mmu.global_symbols.update(self.syscall_int.get_syscall_symbols())

    def load(self, e: 'Executable'):
        return self.mmu.load_bin(e)

    def run_loaded(self, le: 'LoadedExecutable'):
        self.pc = le.run_ptr
        sp, hp = le.stack_heap
        self.regs.set('sp', sp)
        self.regs.set('a0', hp)  # set a0 to point to the heap

        self.__run()

    def __run(self):
        if self.pc <= 0:
            return False
        ins = None
        try:
            while not self.exit:
                self.cycle += 1
                ins = self.mmu.read_ins(self.pc)
                self.pc += 1
                self.__run_instruction(ins)
        except RiscemuBaseException as ex:
            print(FMT_ERROR + "[CPU] excpetion caught at 0x{:08X}: {}:".format(self.pc-1, ins) + FMT_NONE)
            print("      " + ex.message())
            #traceback.print_exception(type(ex), ex, ex.__traceback__)
            if self.conf.debug_on_exception:
                launch_debug_session(self, self.mmu, self.regs,
                                     "Exception encountered, launching debug:".format(self.pc-1))

        print(FMT_CPU + "Program exited with code {}".format(self.exit_code) + FMT_NONE)

    def __run_instruction(self, ins: 'LoadedInstruction'):
        name = '_CPU__instruction_' + ins.name
        if hasattr(self, name):
            getattr(self, name)(ins)
        else:
            # this should never be reached, as unknown instructions are imparsable
            raise RuntimeError("Unknown instruction: {}".format(ins))

    def __parse_mem_ins(self, ins: 'LoadedInstruction') -> Tuple[str, int]:
        """
        parses both rd, rs1, imm and rd, imm(rs1) arguments and returns (rd, imm+rs1)
        (so a register and address tuple for memory instructions)
        """
        if len(ins.args) == 3:
            # handle rd, rs1, imm
            rs1 = ins.get_reg(1)
            imm = ins.get_imm(2)
        else:
            ASSERT_LEN(ins.args, 2)
            ASSERT_IN("(", ins.args[1])
            imm, rs1 = ins.get_imm_reg(1)
            # handle rd, imm(rs1)
        rd = ins.get_reg(0)
        return rd, self.regs.get(rs1) + imm

    def __instruction_lb(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.regs.set(rd, int_from_bytes(self.mmu.read(addr, 1)))

    def __instruction_lh(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.regs.set(rd, int_from_bytes(self.mmu.read(addr, 2)))

    def __instruction_lw(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.regs.set(rd, int_from_bytes(self.mmu.read(addr, 4)))

    def __instruction_lbu(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.regs.set(rd, int_from_bytes(self.mmu.read(addr, 1), unsigned=True))

    def __instruction_lhu(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.regs.set(rd, int_from_bytes(self.mmu.read(addr, 2), unsigned=True))

    def __instruction_sb(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.mmu.write(addr, 1, int_to_bytes(self.regs.get(rd), 1))

    def __instruction_sh(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.mmu.write(addr, 2, int_to_bytes(self.regs.get(rd), 2))

    def __instruction_sw(self, ins: 'LoadedInstruction'):
        rd, addr = self.__parse_mem_ins(ins)
        self.mmu.write(addr, 4, int_to_bytes(self.regs.get(rd), 4))

    def __instruction_sll(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            to_signed(to_unsigned(self.regs.get(src1)) << (self.regs.get(src2) & 0b11111))
        )

    def __instruction_slli(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        imm = ins.get_imm(2)
        self.regs.set(
            dst,
            to_signed(to_unsigned(self.regs.get(src1)) << (imm & 0b11111))
        )

    def __instruction_srl(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            to_signed(to_unsigned(self.regs.get(src1)) >> (self.regs.get(src2) & 0b11111))
        )

    def __instruction_srli(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        imm = ins.get_imm(2)
        self.regs.set(
            dst,
            to_signed(to_unsigned(self.regs.get(src1)) >> (imm & 0b11111))
        )

    def __instruction_sra(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            self.regs.get(src1) >> (self.regs.get(src2) & 0b11111)
        )

    def __instruction_srai(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        imm = ins.get_imm(2)
        self.regs.set(
            dst,
            self.regs.get(src1) >> (imm & 0b11111)
        )

    def __instruction_add(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            self.regs.get(src1) + self.regs.get(src2)
        )

    def __instruction_addi(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        imm = ins.get_imm(2)
        self.regs.set(
            dst,
            self.regs.get(src1) + imm
        )

    def __instruction_sub(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            self.regs.get(src1) - self.regs.get(src2)
        )

    def __instruction_lui(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_auipc(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_xor(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            self.regs.get(src1) ^ self.regs.get(src2)
        )

    def __instruction_xori(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_or(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            self.regs.get(src1) | self.regs.get(src2)
        )

    def __instruction_ori(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_and(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            self.regs.get(src1) & self.regs.get(src2)
        )

    def __instruction_andi(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_slt(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            int(self.regs.get(src1) < self.regs.get(src2))
        )

    def __instruction_slti(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_sltu(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        dst = ins.get_reg(0)
        src1 = ins.get_reg(1)
        src2 = ins.get_reg(2)
        self.regs.set(
            dst,
            int(to_unsigned(self.regs.get(src1)) < to_unsigned(self.regs.get(src2)))
        )

    def __instruction_sltiu(self, ins: 'LoadedInstruction'):
        INS_NOT_IMPLEMENTED(ins)

    def __instruction_beq(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        reg1 = ins.get_reg(0)
        reg2 = ins.get_reg(1)
        dest = ins.get_imm(2)
        if self.regs.get(reg1) == self.regs.get(reg2):
            self.pc = dest

    def __instruction_bne(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        reg1 = ins.get_reg(0)
        reg2 = ins.get_reg(1)
        dest = ins.get_imm(2)
        if self.regs.get(reg1) != self.regs.get(reg2):
            self.pc = dest

    def __instruction_blt(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        reg1 = ins.get_reg(0)
        reg2 = ins.get_reg(1)
        dest = ins.get_imm(2)
        if self.regs.get(reg1) < self.regs.get(reg2):
            self.pc = dest

    def __instruction_bge(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        reg1 = ins.get_reg(0)
        reg2 = ins.get_reg(1)
        dest = ins.get_imm(2)
        if self.regs.get(reg1) >= self.regs.get(reg2):
            self.pc = dest

    def __instruction_bltu(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        reg1 = to_unsigned(ins.get_reg(0))
        reg2 = to_unsigned(ins.get_reg(1))
        dest = ins.get_imm(2)
        if self.regs.get(reg1) < self.regs.get(reg2):
            self.pc = dest

    def __instruction_bgeu(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 3)
        reg1 = to_unsigned(ins.get_reg(0))
        reg2 = to_unsigned(ins.get_reg(1))
        dest = ins.get_imm(2)
        if self.regs.get(reg1) >= self.regs.get(reg2):
            self.pc = dest

    def __instruction_j(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 1)
        addr = ins.get_imm(0)
        self.pc = addr

    def __instruction_jal(self, ins: 'LoadedInstruction'):
        reg = 'ra'  # default register is ra
        if len(ins.args) == 1:
            addr = ins.get_imm(0)
        else:
            ASSERT_LEN(ins.args, 2)
            reg = ins.get_reg(0)
            addr = ins.get_imm(1)
        self.regs.set(reg, self.pc)
        self.pc = addr

    def __instruction_jalr(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 2)
        reg = ins.get_reg(0)
        addr = ins.get_imm(1)
        self.regs.set(reg, self.pc)
        self.pc = addr

    def __instruction_ret(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 0)
        self.pc = self.regs.get('ra')

    def __instruction_ecall(self, ins: 'LoadedInstruction'):
        self.__instruction_scall(ins)

    def __instruction_ebreak(self, ins: 'LoadedInstruction'):
        self.__instruction_sbreak(ins)

    def __instruction_scall(self, ins: 'LoadedInstruction'):
        ASSERT_LEN(ins.args, 0)
        syscall = Syscall(self.regs.get('a7'), self.regs, self)
        self.syscall_int.handle_syscall(syscall)

    def __instruction_sbreak(self, ins: 'LoadedInstruction'):
        launch_debug_session(self, self.mmu, self.regs, "Debug instruction encountered at 0x{:08X}".format(self.pc))

    def __instruction_nop(self, ins: 'LoadedInstruction'):
        pass

    @staticmethod
    def all_instructions():
        for method in vars(CPU):
            if method.startswith('_CPU__instruction_'):
                yield method[18:]

    def __repr__(self):
        return "CPU(pc=0x{:08X}, cycle={})".format(
            self.pc,
            self.cycle
        )