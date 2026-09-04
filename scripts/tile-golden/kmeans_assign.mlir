cuda_tile.module @m {
  entry @kmeans_assign(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 0> : tile<i32>
    %5 = reshape %1 : tile<i32> -> tile<1xi32>
    %6 = broadcast %5 : tile<1xi32> -> tile<4xi32>
    %7 = iota : tile<4xi32>
    %8 = constant <i32: 0> : tile<4xi32>
    %9 = muli %7, %8 : tile<4xi32>
    %10 = addi %6, %9 : tile<4xi32>
    %11 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %12 = broadcast %11 : tile<1xptr<f64>> -> tile<4xptr<f64>>
    %13 = offset %12, %10 : tile<4xptr<f64>>, tile<4xi32> -> tile<4xptr<f64>>
    %14, %15 = load_ptr_tko weak %13 token=%0 : tile<4xptr<f64>> -> tile<4xf64>, token
    %16 = reshape %4 : tile<i32> -> tile<1xi32>
    %17 = broadcast %16 : tile<1xi32> -> tile<4xi32>
    %18 = iota : tile<4xi32>
    %19 = addi %17, %18 : tile<4xi32>
    %20 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %21 = broadcast %20 : tile<1xptr<f64>> -> tile<4xptr<f64>>
    %22 = offset %21, %19 : tile<4xptr<f64>>, tile<4xi32> -> tile<4xptr<f64>>
    %23, %24 = load_ptr_tko weak %22 token=%15 : tile<4xptr<f64>> -> tile<4xf64>, token
    %25 = subf %14, %23 rounding<nearest_even> : tile<4xf64>
    %26 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<4xptr<f64>>
    %28 = offset %27, %10 : tile<4xptr<f64>>, tile<4xi32> -> tile<4xptr<f64>>
    %29, %30 = load_ptr_tko weak %28 token=%24 : tile<4xptr<f64>> -> tile<4xf64>, token
    %31 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %32 = broadcast %31 : tile<1xptr<f64>> -> tile<4xptr<f64>>
    %33 = offset %32, %19 : tile<4xptr<f64>>, tile<4xi32> -> tile<4xptr<f64>>
    %34, %35 = load_ptr_tko weak %33 token=%30 : tile<4xptr<f64>> -> tile<4xf64>, token
    %36 = subf %29, %34 rounding<nearest_even> : tile<4xf64>
    %37 = mulf %25, %25 rounding<nearest_even> : tile<4xf64>
    %38 = mulf %36, %36 rounding<nearest_even> : tile<4xf64>
    %39 = addf %37, %38 rounding<nearest_even> : tile<4xf64>
    %40, %41 = reduce %39, %19 dim=0 identities=[Infinity : f64, -1 : i32] : tile<4xf64>, tile<4xi32> -> tile<f64>, tile<i32> (%42: tile<f64>, %43: tile<f64>, %44: tile<i32>, %45: tile<i32>) {
      %46 = cmpf greater_than ordered %43, %42 : tile<f64> -> tile<i1>
      %47 = select %46, %42, %43 : tile<i1>, tile<f64>
      %48 = select %46, %44, %45 : tile<i1>, tile<i32>
      yield %47, %48 : tile<f64>, tile<i32>
    }
    %49 = constant <i32: 1> : tile<i32>
    %50 = muli %1, %49 : tile<i32>
    %51 = reshape %41 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<1xi32>
    %53 = reshape %50 : tile<i32> -> tile<1xi32>
    %54 = broadcast %53 : tile<1xi32> -> tile<1xi32>
    %55 = iota : tile<1xi32>
    %56 = addi %54, %55 : tile<1xi32>
    %57 = reshape %arg4 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %58 = broadcast %57 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %59 = offset %58, %56 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %60 = store_ptr_tko weak %59, %52 token=%35 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
