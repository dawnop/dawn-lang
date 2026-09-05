cuda_tile.module @m {
  entry @rope(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 16> : tile<i32>
    %7 = addi %5, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %9 = broadcast %8 : tile<1x1xi32> -> tile<32x16xi32>
    %10 = iota : tile<32xi32>
    %11 = reshape %10 : tile<32xi32> -> tile<32x1xi32>
    %12 = broadcast %11 : tile<32x1xi32> -> tile<32x16xi32>
    %13 = constant <i32: 32> : tile<32x16xi32>
    %14 = muli %12, %13 : tile<32x16xi32>
    %15 = addi %9, %14 : tile<32x16xi32>
    %16 = iota : tile<16xi32>
    %17 = reshape %16 : tile<16xi32> -> tile<1x16xi32>
    %18 = broadcast %17 : tile<1x16xi32> -> tile<32x16xi32>
    %19 = addi %15, %18 : tile<32x16xi32>
    %20 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %21 = broadcast %20 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %22 = offset %21, %19 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %23, %24 = load_ptr_tko weak %22 token=%0 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %25 = reshape %7 : tile<i32> -> tile<1x1xi32>
    %26 = broadcast %25 : tile<1x1xi32> -> tile<32x16xi32>
    %27 = iota : tile<32xi32>
    %28 = reshape %27 : tile<32xi32> -> tile<32x1xi32>
    %29 = broadcast %28 : tile<32x1xi32> -> tile<32x16xi32>
    %30 = constant <i32: 32> : tile<32x16xi32>
    %31 = muli %29, %30 : tile<32x16xi32>
    %32 = addi %26, %31 : tile<32x16xi32>
    %33 = iota : tile<16xi32>
    %34 = reshape %33 : tile<16xi32> -> tile<1x16xi32>
    %35 = broadcast %34 : tile<1x16xi32> -> tile<32x16xi32>
    %36 = addi %32, %35 : tile<32x16xi32>
    %37 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %38 = broadcast %37 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %39 = offset %38, %36 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%24 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %42 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %43 = broadcast %42 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %44 = offset %43, %19 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %45, %46 = load_ptr_tko weak %44 token=%41 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %47 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %48 = broadcast %47 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %49 = offset %48, %19 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %50, %51 = load_ptr_tko weak %49 token=%46 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %52 = mulf %23, %45 rounding<nearest_even> : tile<32x16xf64>
    %53 = mulf %40, %50 rounding<nearest_even> : tile<32x16xf64>
    %54 = subf %52, %53 rounding<nearest_even> : tile<32x16xf64>
    %55 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %56 = broadcast %55 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %57 = offset %56, %19 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %58 = store_ptr_tko weak %57, %54 token=%51 : tile<32x16xptr<f64>>, tile<32x16xf64> -> token
    %59 = mulf %40, %45 rounding<nearest_even> : tile<32x16xf64>
    %60 = mulf %23, %50 rounding<nearest_even> : tile<32x16xf64>
    %61 = addf %59, %60 rounding<nearest_even> : tile<32x16xf64>
    %62 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %63 = broadcast %62 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %64 = offset %63, %36 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %65 = store_ptr_tko weak %64, %61 token=%58 : tile<32x16xptr<f64>>, tile<32x16xf64> -> token
    return
  }
}
