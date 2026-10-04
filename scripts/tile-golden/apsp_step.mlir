cuda_tile.module @m {
  entry @apsp_step(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = offset %arg1, %1 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %3, %4 = load_ptr_tko weak %2 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %5 = constant <i32: 16> : tile<i32>
    %6 = muli %3, %5 : tile<i32>
    %7 = constant <i32: 0> : tile<i32>
    %8 = reshape %7 : tile<i32> -> tile<1x1xi32>
    %9 = broadcast %8 : tile<1x1xi32> -> tile<16x16xi32>
    %10 = iota : tile<16xi32>
    %11 = reshape %10 : tile<16xi32> -> tile<16x1xi32>
    %12 = broadcast %11 : tile<16x1xi32> -> tile<16x16xi32>
    %13 = constant <i32: 0> : tile<16x16xi32>
    %14 = muli %12, %13 : tile<16x16xi32>
    %15 = addi %9, %14 : tile<16x16xi32>
    %16 = iota : tile<16xi32>
    %17 = reshape %16 : tile<16xi32> -> tile<1x16xi32>
    %18 = broadcast %17 : tile<1x16xi32> -> tile<16x16xi32>
    %19 = addi %15, %18 : tile<16x16xi32>
    %20 = reshape %6 : tile<i32> -> tile<1x1xi32>
    %21 = broadcast %20 : tile<1x1xi32> -> tile<16x16xi32>
    %22 = addi %21, %19 : tile<16x16xi32>
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
    %38 = reshape %3 : tile<i32> -> tile<1x1xi32>
    %39 = broadcast %38 : tile<1x1xi32> -> tile<16x16xi32>
    %40 = addi %37, %39 : tile<16x16xi32>
    %41 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %42 = broadcast %41 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %43 = offset %42, %40 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %44, %45 = load_ptr_tko weak %43 token=%4 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %46 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %47 = broadcast %46 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %48 = offset %47, %22 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %49, %50 = load_ptr_tko weak %48 token=%45 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %51 = addf %44, %49 rounding<nearest_even> : tile<16x16xf64>
    %52 = constant <i32: 0> : tile<i32>
    %53 = constant <i32: 0> : tile<i32>
    %54 = reshape %53 : tile<i32> -> tile<1x1xi32>
    %55 = broadcast %54 : tile<1x1xi32> -> tile<16x16xi32>
    %56 = iota : tile<16xi32>
    %57 = reshape %56 : tile<16xi32> -> tile<16x1xi32>
    %58 = broadcast %57 : tile<16x1xi32> -> tile<16x16xi32>
    %59 = constant <i32: 16> : tile<16x16xi32>
    %60 = muli %58, %59 : tile<16x16xi32>
    %61 = addi %55, %60 : tile<16x16xi32>
    %62 = iota : tile<16xi32>
    %63 = reshape %62 : tile<16xi32> -> tile<1x16xi32>
    %64 = broadcast %63 : tile<1x16xi32> -> tile<16x16xi32>
    %65 = addi %61, %64 : tile<16x16xi32>
    %66 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %67 = broadcast %66 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %68 = offset %67, %65 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %69, %70 = load_ptr_tko weak %68 token=%50 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %71 = minf %69, %51 : tile<16x16xf64>
    %72 = reshape %52 : tile<i32> -> tile<1x1xi32>
    %73 = broadcast %72 : tile<1x1xi32> -> tile<16x16xi32>
    %74 = iota : tile<16xi32>
    %75 = reshape %74 : tile<16xi32> -> tile<16x1xi32>
    %76 = broadcast %75 : tile<16x1xi32> -> tile<16x16xi32>
    %77 = constant <i32: 16> : tile<16x16xi32>
    %78 = muli %76, %77 : tile<16x16xi32>
    %79 = addi %73, %78 : tile<16x16xi32>
    %80 = iota : tile<16xi32>
    %81 = reshape %80 : tile<16xi32> -> tile<1x16xi32>
    %82 = broadcast %81 : tile<1x16xi32> -> tile<16x16xi32>
    %83 = addi %79, %82 : tile<16x16xi32>
    %84 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %85 = broadcast %84 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %86 = offset %85, %83 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %87 = store_ptr_tko weak %86, %71 token=%70 : tile<16x16xptr<f64>>, tile<16x16xf64> -> token
    return
  }
}
