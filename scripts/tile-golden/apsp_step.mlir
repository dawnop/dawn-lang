cuda_tile.module @m {
  entry @apsp_step(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<16x16xi32>
    %2 = reshape %arg1 : tile<ptr<i32>> -> tile<1x1xptr<i32>>
    %3 = broadcast %2 : tile<1x1xptr<i32>> -> tile<16x16xptr<i32>>
    %4 = offset %3, %1 : tile<16x16xptr<i32>>, tile<16x16xi32> -> tile<16x16xptr<i32>>
    %5, %6 = load_ptr_tko weak %4 token=%0 : tile<16x16xptr<i32>> -> tile<16x16xi32>, token
    %7 = constant <i32: 16> : tile<16x16xi32>
    %8 = muli %5, %7 : tile<16x16xi32>
    %9 = constant <i32: 0> : tile<i32>
    %10 = reshape %9 : tile<i32> -> tile<1x1xi32>
    %11 = broadcast %10 : tile<1x1xi32> -> tile<16x16xi32>
    %12 = iota : tile<16xi32>
    %13 = reshape %12 : tile<16xi32> -> tile<16x1xi32>
    %14 = broadcast %13 : tile<16x1xi32> -> tile<16x16xi32>
    %15 = constant <i32: 0> : tile<16x16xi32>
    %16 = muli %14, %15 : tile<16x16xi32>
    %17 = addi %11, %16 : tile<16x16xi32>
    %18 = iota : tile<16xi32>
    %19 = reshape %18 : tile<16xi32> -> tile<1x16xi32>
    %20 = broadcast %19 : tile<1x16xi32> -> tile<16x16xi32>
    %21 = addi %17, %20 : tile<16x16xi32>
    %22 = addi %8, %21 : tile<16x16xi32>
    %23 = constant <i32: 0> : tile<i32>
    %24 = reshape %23 : tile<i32> -> tile<1x1xi32>
    %25 = broadcast %24 : tile<1x1xi32> -> tile<16x16xi32>
    %26 = iota : tile<16xi32>
    %27 = reshape %26 : tile<16xi32> -> tile<16x1xi32>
    %28 = broadcast %27 : tile<16x1xi32> -> tile<16x16xi32>
    %29 = constant <i32: 16> : tile<16x16xi32>
    %30 = muli %28, %29 : tile<16x16xi32>
    %31 = addi %25, %30 : tile<16x16xi32>
    %32 = iota : tile<16xi32>
    %33 = reshape %32 : tile<16xi32> -> tile<1x16xi32>
    %34 = broadcast %33 : tile<1x16xi32> -> tile<16x16xi32>
    %35 = constant <i32: 0> : tile<16x16xi32>
    %36 = muli %34, %35 : tile<16x16xi32>
    %37 = addi %31, %36 : tile<16x16xi32>
    %38 = addi %37, %5 : tile<16x16xi32>
    %39 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %40 = broadcast %39 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %41 = offset %40, %38 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %42, %43 = load_ptr_tko weak %41 token=%6 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %44 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %45 = broadcast %44 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %46 = offset %45, %22 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %47, %48 = load_ptr_tko weak %46 token=%43 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %49 = addf %42, %47 rounding<nearest_even> : tile<16x16xf64>
    %50 = constant <i32: 0> : tile<i32>
    %51 = constant <i32: 0> : tile<i32>
    %52 = reshape %51 : tile<i32> -> tile<1x1xi32>
    %53 = broadcast %52 : tile<1x1xi32> -> tile<16x16xi32>
    %54 = iota : tile<16xi32>
    %55 = reshape %54 : tile<16xi32> -> tile<16x1xi32>
    %56 = broadcast %55 : tile<16x1xi32> -> tile<16x16xi32>
    %57 = constant <i32: 16> : tile<16x16xi32>
    %58 = muli %56, %57 : tile<16x16xi32>
    %59 = addi %53, %58 : tile<16x16xi32>
    %60 = iota : tile<16xi32>
    %61 = reshape %60 : tile<16xi32> -> tile<1x16xi32>
    %62 = broadcast %61 : tile<1x16xi32> -> tile<16x16xi32>
    %63 = addi %59, %62 : tile<16x16xi32>
    %64 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %65 = broadcast %64 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %66 = offset %65, %63 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %67, %68 = load_ptr_tko weak %66 token=%48 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %69 = minf %67, %49 : tile<16x16xf64>
    %70 = reshape %50 : tile<i32> -> tile<1x1xi32>
    %71 = broadcast %70 : tile<1x1xi32> -> tile<16x16xi32>
    %72 = iota : tile<16xi32>
    %73 = reshape %72 : tile<16xi32> -> tile<16x1xi32>
    %74 = broadcast %73 : tile<16x1xi32> -> tile<16x16xi32>
    %75 = constant <i32: 16> : tile<16x16xi32>
    %76 = muli %74, %75 : tile<16x16xi32>
    %77 = addi %71, %76 : tile<16x16xi32>
    %78 = iota : tile<16xi32>
    %79 = reshape %78 : tile<16xi32> -> tile<1x16xi32>
    %80 = broadcast %79 : tile<1x16xi32> -> tile<16x16xi32>
    %81 = addi %77, %80 : tile<16x16xi32>
    %82 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %83 = broadcast %82 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %84 = offset %83, %81 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %85 = store_ptr_tko weak %84, %69 token=%68 : tile<16x16xptr<f64>>, tile<16x16xf64> -> token
    return
  }
}
