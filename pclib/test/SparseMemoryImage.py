#=========================================================================
# Sparse Memory Image
#=========================================================================
# This module contains a class for representing ELF binary which would be
# loaded into a TestMemory object.

from __future__ import print_function

import subprocess
import tempfile

from pymtl import *

#-------------------------------------------------------------------------------
# Global Variables
#-------------------------------------------------------------------------------

# Command to compile using maven-gcc

compile_cmd  = "maven-gcc -Wall -MMD -MP -nostartfiles "
compile_cmd += "{asm_file} -o {target} -T {linker_script} "

# Command to execute maven-objdump

objdump_cmd  = "maven-objdump -DC --disassemble-zeroes --section=.text "
objdump_cmd += "--section=.data --section=.sdata --section=.xcpthandler "
objdump_cmd += "--section=.init --section=.fini --section=.ctors "
objdump_cmd += "--section=.dtors --section=.eh_frame --section=.jcr "
objdump_cmd += "--section=.sbss --section=.bss --section=.rodata "
objdump_cmd += "{filename} > {dump}"

# Test linker script

test_ld = """
OUTPUT_ARCH( "mips:maven" )

ENTRY( _test )

SECTIONS
{

  . = 0x00000004;
  .xcpthandler :
  {
    *(.xcpthandler)
  }

  . = 0x00000400;
  .text :
  {
    *(.text)
  }

  .data :
  {
    *(.data)
  }

  _end = .;
}
"""

#-------------------------------------------------------------------------------
# Utility Functions
#-------------------------------------------------------------------------------

def execute( cmd ):
  # Throws a CalledProcessError if the command is not available; don't catch,
  # let this propagate up to the user!
  subprocess.check_call( cmd, shell=True )

#-------------------------------------------------------------------------------
# Sparse Memory Image Class
#-------------------------------------------------------------------------------

class SparseMemoryImage:

  #-----------------------------------------------------------------------------
  # Constructor
  #-----------------------------------------------------------------------------
  #
  # By default the constructor expects an assembly string to create a
  # SparseMemoryImage instance. We could also pass a list of lists, binary
  # filename or a binary file handle.

  def __init__( s, asm_str = None, labels_list = None,
                bin_filename = None, bin_filehandle = None, vmh_filename = None,
                dump_asm = None, dump_bin = None ):

    # sparse memory : list of list of lists
    # a single entry in the class represents a label along with
    # the bytes of memory stored in the label.
    # [ label_addr, [list of bytes] ]

    s.sparse_memory_img = [ ]

    if labels_list is not None:

      # assign the obtained list of list to the sparse memory image data
      # structure

      s.sparse_memory_img.extend( labels_list )

    elif vmh_filename is not None:

      vmh_fd = open(vmh_filename)
      addr = None
      current_list = None

      for line in vmh_fd:

        # Search for addr labels

        if line[0] == '@':
          hex_str, slash, label = line[1:].split()
          addr = int(hex_str, 16)
          current_list = []
          #print( hex(addr) )
          s.sparse_memory_img.append( [ addr, current_list ] )

        # We have an addr label and the line is not blank, get the data

        elif addr and line.strip():
          hex_str = line.split()[0]
          value = int(hex_str, 16)
          current_list.append( value )

      #print( s.sparse_memory_img )


    elif bin_filename is not None:

      # Create a temporary file for capturing objdump output and pass the
      # filename to objdump command and execute the objdump command

      dump = tempfile.NamedTemporaryFile( mode = 'w+' )
      cmd  = objdump_cmd.format( filename = bin_filename, dump = dump.name )
      execute( cmd )

      # move to the start of the temp file before parsing
      dump.seek( 0 )

      # Based on objdump2vmh.py
      # fill the sparse memory labels

      bytes_list = []
      in_label = False
      for line in dump:

        split_line = line.split()

        # start of a label

        if( line.find( ">:\n" ) >= 0 ):

          in_label   = True

          # Determine if the virtual address is a halfword or fullword.
          # Only write out this line if it's word aligned ignore every
          # other .half declaration

          vaddr = int( split_line[0], 16 )
          if ( vaddr % 4 ) == 0:
            label_addr = int( split_line[0], 16 )
          # label_name = split_line[1][:-1]

        elif in_label:

          if line == "\n":

            # end of a label
            s.sparse_memory_img.append( [ label_addr, bytes_list ] )
            bytes_list = []
            in_label = False

          else:

            # append bytes insided a label using a Bits object

            inst_bits      = Bits( 32, int( split_line[1], 16) )

            # deconstruct the 32-bit individual into its constituent bytes
            # since we need to extend a list of bytes.

            for i in range( 4 ):
              bytes_list.append( inst_bits[i*8:i*8+8].uint() )

      # we iterate through all the lines in the file and the for loop
      # exits the loop when it reaches the EOF. The last label that was
      # detected is not yet appended to the sparse memory image.
      # Append the last label
      s.sparse_memory_img.append( [ label_addr, bytes_list ] )

      # close temporary file

      dump.close()

    elif bin_filehandle is not None:

      # actions when a binary file handle is passed in

      pass

    elif asm_str is not None:
      # actions when an assembly string is passed

      # assembly test

      asm_test = asm_str

      # create a temporary assembly test file

      asm_file = tempfile.NamedTemporaryFile( mode = 'w+t', suffix = '.s' )
      asm_file.write( asm_test )

      # need to move the file pointer to the start of the file for reading
      # the file from start

      asm_file.seek( 0 )

      # temporary binary file

      target = tempfile.NamedTemporaryFile( mode = 'w+b' )

      # create a temporary linker script

      ld_script = tempfile.NamedTemporaryFile( mode = 'w+t', suffix = '.ld' )
      ld_script.write( test_ld )
      ld_script.seek( 0 )

      # compile the assembly test

      cmd = compile_cmd.format( asm_file      = asm_file.name,
                                target        = target.name,
                                linker_script = ld_script.name )
      execute( cmd )

      # Create a temporary file for capturing objdump output and pass the
      # filename to objdump command and execute the objdump command

      dump = tempfile.NamedTemporaryFile( mode = 'w+' )

      target.seek( 0 )
      cmd  = objdump_cmd.format( filename = target.name, dump = dump.name )

      execute( cmd )

      # move to the start of the temp file before parsing
      dump.seek( 0 )

      # Based on objdump2vmh.py
      # fill the sparse memory labels

      bytes_list = []
      in_label = False
      for line in dump:

        split_line = line.split()

        # start of a label

        if( line.find( ">:\n" ) >= 0 ):

          in_label   = True

          # Determine if the virtual address is a halfword or fullword.
          # Only write out this line if it's word aligned ignore every
          # other .half declaration

          vaddr = int( split_line[0], 16 )
          if ( vaddr % 4 ) == 0:
            label_addr = int( split_line[0], 16 )
          # label_name = split_line[1][:-1]

        elif in_label:

          if line == "\n":

            # end of a label
            s.sparse_memory_img.append( [ label_addr, bytes_list ] )
            bytes_list = []
            in_label = False

          else:

            # append bytes insided a label using a Bits object

            inst_bits      = Bits( 32, int( split_line[1], 16) )

            # deconstruct the 32-bit individual into its constituent bytes
            # since we need to extend a list of bytes.

            for i in range( 4 ):
              bytes_list.append( inst_bits[i*8:i*8+8].uint() )

      # we iterate through all the lines in the file and the for loop
      # exits the loop when it reaches the EOF. The last label that was
      # detected is not yet appended to the sparse memory image.
      # Append the last label

      s.sparse_memory_img.append( [ label_addr, bytes_list ] )

      # Dump the assembly file created

      if dump_asm is not None:
        asm_dump_file = open( dump_asm, 'w' )

        # seek to the start and dump
        asm_file.seek( 0 )
        asm_dump_file.write( asm_file.read() )
        asm_dump_file.close()

      # Dump the binary file

      if dump_bin is not None:

        cmd = compile_cmd.format( asm_file      = asm_file.name,
                                  target        = dump_bin,
                                  linker_script = ld_script.name )
        execute( cmd )

      # close temporary files

      asm_file.close()
      target.close()
      ld_script.close()
      dump.close()

  #-----------------------------------------------------------------------------
  # overload equal comparison
  #-----------------------------------------------------------------------------

  def __eq__( s, other ):
     
    assert isinstance( other, SparseMemoryImage ) == 1
    return s.sparse_memory_img == other.sparse_memory_img

  #-----------------------------------------------------------------------------
  # load label method
  #-----------------------------------------------------------------------------

  def load_label( s, label_list ):
    s.sparse_memory_img.append( label_list )

  #-----------------------------------------------------------------------------
  # read label method
  #-----------------------------------------------------------------------------

  def read_label( s, label_addr ):
    return s.sparse_memory_img[ label_addr ]

  #-----------------------------------------------------------------------------
  # num labels method
  #-----------------------------------------------------------------------------

  def num_labels( s ):
    return len( s.sparse_memory_img )
