cuda_tile.module @m {
  entry @attr_ucmp(%arg0: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 256> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<128xi32>
    %7 = constant <i32: 2147483632> : tile<i32>
    %8 = constant <i32: -2147483632> : tile<i32>
    %9 = constant <i32: 1> : tile<i32>
    %10, %11 = for %12 in (%7 to %8, step %9) : tile<i32> iter_values(%13 = %6, %14 = %0) -> (tile<128xi32>, token) {
      %15 = constant <i32: 1> : tile<128xi32>
      %16 = addi %13, %15 : tile<128xi32>
      continue %16, %14 : tile<128xi32>, token
    }
    %17 = constant <i32: 2147483632> : tile<i32>
    %18 = constant <i32: -2147483632> : tile<i32>
    %19 = constant <i32: 1> : tile<i32>
    %20, %21 = for %22 in (%17 to %18, step %19) unsigned : tile<i32> iter_values(%23 = %6, %24 = %11) -> (tile<128xi32>, token) {
      %25 = constant <i32: 1> : tile<128xi32>
      %26 = addi %23, %25 : tile<128xi32>
      continue %26, %24 : tile<128xi32>, token
    }
    %27 = reshape %5 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<128xi32>
    %29 = iota : tile<128xi32>
    %30 = addi %28, %29 : tile<128xi32>
    %31 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %32 = broadcast %31 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %33 = offset %32, %30 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %34 = store_ptr_tko weak %33, %10 token=%21 : tile<128xptr<i32>>, tile<128xi32> -> token
    %35 = constant <i32: 128> : tile<i32>
    %36 = addi %5, %35 : tile<i32>
    %37 = reshape %36 : tile<i32> -> tile<1xi32>
    %38 = broadcast %37 : tile<1xi32> -> tile<128xi32>
    %39 = iota : tile<128xi32>
    %40 = addi %38, %39 : tile<128xi32>
    %41 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %42 = broadcast %41 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %43 = offset %42, %40 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %44 = store_ptr_tko weak %43, %20 token=%34 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
