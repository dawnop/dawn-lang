cuda_tile.module @m {
  entry @batched_matmul(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10 = constant <i32: 4096> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = constant <i32: 2048> : tile<i32>
    %13 = muli %1, %12 : tile<i32>
    %14 = addi %11, %13 : tile<i32>
    %15 = constant <i32: 4096> : tile<i32>
    %16 = muli %9, %15 : tile<i32>
    %17 = constant <i32: 32> : tile<i32>
    %18 = muli %5, %17 : tile<i32>
    %19 = addi %16, %18 : tile<i32>
    %20 = constant <f64: 0.0> : tile<32x32xf64>
    %21 = constant <i32: 0> : tile<i32>
    %22 = constant <i32: 2> : tile<i32>
    %23 = constant <i32: 1> : tile<i32>
    %24, %25 = for %26 in (%21 to %22, step %23) : tile<i32> iter_values(%27 = %20, %28 = %0) -> (tile<32x32xf64>, token) {
      %29 = constant <i32: 32> : tile<i32>
      %30 = muli %26, %29 : tile<i32>
      %31 = addi %14, %30 : tile<i32>
      %32 = reshape %31 : tile<i32> -> tile<1x1xi32>
      %33 = broadcast %32 : tile<1x1xi32> -> tile<32x32xi32>
      %34 = iota : tile<32xi32>
      %35 = reshape %34 : tile<32xi32> -> tile<32x1xi32>
      %36 = broadcast %35 : tile<32x1xi32> -> tile<32x32xi32>
      %37 = constant <i32: 64> : tile<32x32xi32>
      %38 = muli %36, %37 : tile<32x32xi32>
      %39 = addi %33, %38 : tile<32x32xi32>
      %40 = iota : tile<32xi32>
      %41 = reshape %40 : tile<32xi32> -> tile<1x32xi32>
      %42 = broadcast %41 : tile<1x32xi32> -> tile<32x32xi32>
      %43 = addi %39, %42 : tile<32x32xi32>
      %44 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %45 = broadcast %44 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %46 = offset %45, %43 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %47, %48 = load_ptr_tko weak %46 token=%28 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %49 = constant <i32: 2048> : tile<i32>
      %50 = muli %26, %49 : tile<i32>
      %51 = addi %19, %50 : tile<i32>
      %52 = reshape %51 : tile<i32> -> tile<1x1xi32>
      %53 = broadcast %52 : tile<1x1xi32> -> tile<32x32xi32>
      %54 = iota : tile<32xi32>
      %55 = reshape %54 : tile<32xi32> -> tile<32x1xi32>
      %56 = broadcast %55 : tile<32x1xi32> -> tile<32x32xi32>
      %57 = constant <i32: 64> : tile<32x32xi32>
      %58 = muli %56, %57 : tile<32x32xi32>
      %59 = addi %53, %58 : tile<32x32xi32>
      %60 = iota : tile<32xi32>
      %61 = reshape %60 : tile<32xi32> -> tile<1x32xi32>
      %62 = broadcast %61 : tile<1x32xi32> -> tile<32x32xi32>
      %63 = addi %59, %62 : tile<32x32xi32>
      %64 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %65 = broadcast %64 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %66 = offset %65, %63 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %67, %68 = load_ptr_tko weak %66 token=%48 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %69 = mmaf %47, %67, %27 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %69, %68 : tile<32x32xf64>, token
    }
    %70 = constant <i32: 4096> : tile<i32>
    %71 = muli %9, %70 : tile<i32>
    %72 = constant <i32: 2048> : tile<i32>
    %73 = muli %1, %72 : tile<i32>
    %74 = addi %71, %73 : tile<i32>
    %75 = constant <i32: 32> : tile<i32>
    %76 = muli %5, %75 : tile<i32>
    %77 = addi %74, %76 : tile<i32>
    %78 = reshape %77 : tile<i32> -> tile<1x1xi32>
    %79 = broadcast %78 : tile<1x1xi32> -> tile<32x32xi32>
    %80 = iota : tile<32xi32>
    %81 = reshape %80 : tile<32xi32> -> tile<32x1xi32>
    %82 = broadcast %81 : tile<32x1xi32> -> tile<32x32xi32>
    %83 = constant <i32: 64> : tile<32x32xi32>
    %84 = muli %82, %83 : tile<32x32xi32>
    %85 = addi %79, %84 : tile<32x32xi32>
    %86 = iota : tile<32xi32>
    %87 = reshape %86 : tile<32xi32> -> tile<1x32xi32>
    %88 = broadcast %87 : tile<1x32xi32> -> tile<32x32xi32>
    %89 = addi %85, %88 : tile<32x32xi32>
    %90 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %91 = broadcast %90 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %92 = offset %91, %89 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %93 = store_ptr_tko weak %92, %24 token=%25 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
