cuda_tile.module @m {
  entry @invert(%arg0: tile<ptr<i8>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 1000> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <i8: 0> : tile<128xi8>
    %13 = reshape %arg0 : tile<ptr<i8>> -> tile<1xptr<i8>>
    %14 = broadcast %13 : tile<1xptr<i8>> -> tile<128xptr<i8>>
    %15 = offset %14, %9 : tile<128xptr<i8>>, tile<128xi32> -> tile<128xptr<i8>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<i8>>, tile<128xi1>, tile<128xi8> -> tile<128xi8>, token
    %18 = constant <i32: 255> : tile<128xi32>
    %19 = exti %16 unsigned : tile<128xi8> -> tile<128xi32>
    %20 = subi %18, %19 : tile<128xi32>
    %21 = trunci %20 : tile<128xi32> -> tile<128xi8>
    %22 = store_ptr_tko weak %15, %21, %11 token=%17 : tile<128xptr<i8>>, tile<128xi8>, tile<128xi1> -> token
    return
  }
}
