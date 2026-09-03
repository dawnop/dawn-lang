cuda_tile.module @m {
  entry @transpose(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 2048> : tile<i32>
    %8 = muli %1, %7 : tile<i32>
    %9 = constant <i32: 32> : tile<i32>
    %10 = muli %5, %9 : tile<i32>
    %11 = addi %8, %10 : tile<i32>
    %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
    %13 = broadcast %12 : tile<1x1xi32> -> tile<32x32xi32>
    %14 = iota : tile<32xi32>
    %15 = reshape %14 : tile<32xi32> -> tile<32x1xi32>
    %16 = broadcast %15 : tile<32x1xi32> -> tile<32x32xi32>
    %17 = constant <i32: 64> : tile<32x32xi32>
    %18 = muli %16, %17 : tile<32x32xi32>
    %19 = addi %13, %18 : tile<32x32xi32>
    %20 = iota : tile<32xi32>
    %21 = reshape %20 : tile<32xi32> -> tile<1x32xi32>
    %22 = broadcast %21 : tile<1x32xi32> -> tile<32x32xi32>
    %23 = addi %19, %22 : tile<32x32xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %26 = offset %25, %23 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %27, %28 = load_ptr_tko weak %26 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %29 = constant <i32: 4096> : tile<i32>
    %30 = muli %5, %29 : tile<i32>
    %31 = constant <i32: 32> : tile<i32>
    %32 = muli %1, %31 : tile<i32>
    %33 = addi %30, %32 : tile<i32>
    %34 = reshape %33 : tile<i32> -> tile<1x1xi32>
    %35 = broadcast %34 : tile<1x1xi32> -> tile<32x32xi32>
    %36 = iota : tile<32xi32>
    %37 = reshape %36 : tile<32xi32> -> tile<32x1xi32>
    %38 = broadcast %37 : tile<32x1xi32> -> tile<32x32xi32>
    %39 = addi %35, %38 : tile<32x32xi32>
    %40 = iota : tile<32xi32>
    %41 = reshape %40 : tile<32xi32> -> tile<1x32xi32>
    %42 = broadcast %41 : tile<1x32xi32> -> tile<32x32xi32>
    %43 = constant <i32: 128> : tile<32x32xi32>
    %44 = muli %42, %43 : tile<32x32xi32>
    %45 = addi %39, %44 : tile<32x32xi32>
    %46 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %47 = broadcast %46 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %48 = offset %47, %45 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %49 = store_ptr_tko weak %48, %27 token=%28 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
