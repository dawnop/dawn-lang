cuda_tile.module @m {
  entry @kmeans_centroid(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<i32>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 0> : tile<i32>
    %5 = constant <f64: 0.0> : tile<64xf64>
    %6 = reshape %4 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<64xptr<i32>>
    %12 = offset %11, %9 : tile<64xptr<i32>>, tile<64xi32> -> tile<64xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<64xptr<i32>> -> tile<64xi32>, token
    %15 = reshape %1 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<64xi32>
    %17 = iota : tile<64xi32>
    %18 = constant <i32: 0> : tile<64xi32>
    %19 = muli %17, %18 : tile<64xi32>
    %20 = addi %16, %19 : tile<64xi32>
    %21 = cmpi equal %13, %20, signed : tile<64xi32> -> tile<64xi1>
    %22 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %24 = offset %23, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %25, %26 = load_ptr_tko weak %24 token=%14 : tile<64xptr<f64>> -> tile<64xf64>, token
    %27 = select %21, %25, %5 : tile<64xi1>, tile<64xf64>
    %28 = reduce %27 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%29: tile<f64>, %30: tile<f64>) {
      %31 = addf %29, %30 rounding<nearest_even> : tile<f64>
      yield %31 : tile<f64>
    }
    %32 = reshape %28 : tile<f64> -> tile<1xf64>
    %33 = broadcast %32 : tile<1xf64> -> tile<1xf64>
    %34 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %35 = broadcast %34 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %36 = offset %35, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %37, %38 = load_ptr_tko weak %36 token=%26 : tile<64xptr<f64>> -> tile<64xf64>, token
    %39 = select %21, %37, %5 : tile<64xi1>, tile<64xf64>
    %40 = reduce %39 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%41: tile<f64>, %42: tile<f64>) {
      %43 = addf %41, %42 rounding<nearest_even> : tile<f64>
      yield %43 : tile<f64>
    }
    %44 = reshape %40 : tile<f64> -> tile<1xf64>
    %45 = broadcast %44 : tile<1xf64> -> tile<1xf64>
    %46 = constant <f64: 1.0> : tile<64xf64>
    %47 = select %21, %46, %5 : tile<64xi1>, tile<64xf64>
    %48 = reduce %47 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%49: tile<f64>, %50: tile<f64>) {
      %51 = addf %49, %50 rounding<nearest_even> : tile<f64>
      yield %51 : tile<f64>
    }
    %52 = reshape %48 : tile<f64> -> tile<1xf64>
    %53 = broadcast %52 : tile<1xf64> -> tile<1xf64>
    %54 = constant <f64: 0.0> : tile<1xf64>
    %55 = cmpf greater_than ordered %53, %54 : tile<1xf64> -> tile<1xi1>
    %56 = constant <f64: 1.0> : tile<1xf64>
    %57 = select %55, %53, %56 : tile<1xi1>, tile<1xf64>
    %58 = constant <i32: 1> : tile<i32>
    %59 = muli %1, %58 : tile<i32>
    %60 = reshape %1 : tile<i32> -> tile<1xi32>
    %61 = broadcast %60 : tile<1xi32> -> tile<1xi32>
    %62 = iota : tile<1xi32>
    %63 = constant <i32: 0> : tile<1xi32>
    %64 = muli %62, %63 : tile<1xi32>
    %65 = addi %61, %64 : tile<1xi32>
    %66 = constant <i32: 0> : tile<1xi32>
    %67 = cmpi greater_than_or_equal %65, %66, signed : tile<1xi32> -> tile<1xi1>
    %68 = constant <i32: 4> : tile<1xi32>
    %69 = cmpi less_than %65, %68, signed : tile<1xi32> -> tile<1xi1>
    %70 = constant <i1: 0> : tile<1xi1>
    %71 = select %67, %69, %70 : tile<1xi1>, tile<1xi1>
    %72 = constant <f64: 0.0> : tile<1xf64>
    %73 = divf %33, %57 rounding<nearest_even> : tile<1xf64>
    %74 = reshape %59 : tile<i32> -> tile<1xi32>
    %75 = broadcast %74 : tile<1xi32> -> tile<1xi32>
    %76 = iota : tile<1xi32>
    %77 = addi %75, %76 : tile<1xi32>
    %78 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %79 = broadcast %78 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %80 = offset %79, %77 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %81, %82 = load_ptr_tko weak %80, %71, %72 token=%38 : tile<1xptr<f64>>, tile<1xi1>, tile<1xf64> -> tile<1xf64>, token
    %83 = select %55, %73, %81 : tile<1xi1>, tile<1xf64>
    %84 = store_ptr_tko weak %80, %83, %71 token=%82 : tile<1xptr<f64>>, tile<1xf64>, tile<1xi1> -> token
    %85 = divf %45, %57 rounding<nearest_even> : tile<1xf64>
    %86 = reshape %arg4 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %87 = broadcast %86 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %88 = offset %87, %77 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %89, %90 = load_ptr_tko weak %88, %71, %72 token=%84 : tile<1xptr<f64>>, tile<1xi1>, tile<1xf64> -> tile<1xf64>, token
    %91 = select %55, %85, %89 : tile<1xi1>, tile<1xf64>
    %92 = store_ptr_tko weak %88, %91, %71 token=%90 : tile<1xptr<f64>>, tile<1xf64>, tile<1xi1> -> token
    return
  }
}
